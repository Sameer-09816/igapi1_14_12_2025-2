from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import List, Optional
from bs4 import BeautifulSoup
import httpx
import execjs
import re
from urllib.parse import urlparse
import contextlib

# --- Pydantic Models ---

class MediaItem(BaseModel):
    caption: Optional[str] = None
    media_url: str
    source_type: str = "post"
    thumbnail_url: Optional[str] = None
    timestamp: Optional[str] = None
    type: str

class InstagramResponse(BaseModel):
    media: List[MediaItem]
    media_count: int
    requested_url: str
    source_of_data: str = "SnapInsta"
    status: str
    username: str

# --- Constants ---

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://snapinsta.to/',
    'Origin': 'https://snapinsta.to',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'X-Requested-With': 'XMLHttpRequest',
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9'
}

# --- Lifecycle (Persistent Connection) ---

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(headers=HEADERS, timeout=30.0, follow_redirects=True)
    yield
    await app.state.client.aclose()

app = FastAPI(title="IG Downloader API", lifespan=lifespan)

# --- Helpers ---

def extract_username(url: str) -> str:
    try:
        path = urlparse(url).path
        parts = [p for p in path.strip('/').split('/') if p]
        if 'stories' in parts:
            return parts[1] if len(parts) > 1 else "instagram_user"
        if len(parts) > 1 and parts[0] not in ['p', 'reel', 'tv', 'stories']:
            return parts[0]
        return "instagram_user"
    except:
        return "instagram_user"

def decode_js_logic(obfuscated_js: str) -> str:
    """Run in threadpool to un-packer JS"""
    if "eval(" in obfuscated_js:
        js_to_run = obfuscated_js.replace("eval(function", "return (function")
        if "eval(function(h,u,n,t,e,r)" in obfuscated_js:
            js_to_run = obfuscated_js.replace("eval(function(h,u,n,t,e,r)", "return (function(h,u,n,t,e,r)")
        
        ctx = execjs.compile(f"function run() {{ {js_to_run} }}")
        return ctx.call("run")
    return obfuscated_js

# --- Endpoint ---

@app.get("/api/download", response_model=InstagramResponse)
async def download_instagram(url: str = Query(..., description="Instagram URL")):
    client: httpx.AsyncClient = app.state.client
    
    # 1. Verify / Get Token
    try:
        verify_resp = await client.post("https://snapinsta.to/api/userverify", data={'url': url})
        verify_json = verify_resp.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Connection Error: {str(e)}")

    if not verify_json.get('success'):
        raise HTTPException(status_code=400, detail="Invalid URL or Verification Failed")
    
    token = verify_json.get('token')

    # 2. Ajax Search
    try:
        search_resp = await client.post(
            "https://snapinsta.to/api/ajaxSearch", 
            data={'q': url, 't': 'media', 'lang': 'en', 'v': 'v2', 'cftoken': token}
        )
        search_json = search_resp.json()
    except Exception:
        raise HTTPException(status_code=500, detail="Search API Error")

    if search_json.get('status') != 'ok' or not search_json.get('data'):
        raise HTTPException(status_code=404, detail="Content not found")

    # 3. Decode JS
    try:
        decoded_script = await run_in_threadpool(decode_js_logic, search_json.get('data'))
    except Exception:
        raise HTTPException(status_code=500, detail="JS Decoding Failed")

    # 4. Extract HTML
    html_match = re.search(r'innerHTML\s*=\s*"(.*?)";', decoded_script, re.DOTALL | re.IGNORECASE)
    html_content = html_match.group(1).replace(r'\"', '"').replace(r'\/', '/') if html_match else decoded_script

    # 5. Parse HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    media_list = []
    
    download_items = soup.find_all('div', class_='download-items')

    for item in download_items:
        # --- FIX: Thumbnail Logic ---
        thumbnail_url = None
        thumb_div = item.find('div', class_='download-items__thumb')
        
        if thumb_div:
            img_tag = thumb_div.find('img')
            if img_tag:
                # Priority 1: Check 'data-src' (Lazy Loading)
                if img_tag.get('data-src'):
                    thumbnail_url = img_tag.get('data-src')
                # Priority 2: Check 'src' but ignore loader.gif
                elif img_tag.get('src'):
                    src_val = img_tag.get('src')
                    if "loader.gif" not in src_val and "imgs/" not in src_val:
                        thumbnail_url = src_val

        # --- Extract Media URL ---
        btn_div = item.find('div', class_='download-items__btn')
        media_url = None
        if btn_div:
            a_tag = btn_div.find('a', href=True)
            if a_tag:
                media_url = a_tag['href']
                if media_url.startswith(r"\'") and media_url.endswith(r"\'"):
                    media_url = media_url[2:-2]

        if media_url:
            media_type = 'video' if '.mp4' in media_url or 'video' in media_url else 'image'
            
            # --- FIX: Fallback for Images ---
            # If it's an image and we still have no valid thumbnail (or it's the loader),
            # the media_url IS the image, so use that as thumbnail.
            if media_type == 'image':
                if not thumbnail_url or "loader.gif" in str(thumbnail_url):
                    thumbnail_url = media_url

            media_list.append(MediaItem(
                media_url=media_url,
                thumbnail_url=thumbnail_url,
                type=media_type
            ))

    # Fallback for unexpected layouts
    if not media_list:
        all_links = soup.find_all('a', href=True)
        for link in all_links:
            href = link['href']
            if any(x in href for x in ["fbcdn", "cdninstagram", "snapinsta"]):
                m_type = 'video' if '.mp4' in href else 'image'
                media_list.append(MediaItem(
                    media_url=href,
                    thumbnail_url=href if m_type == 'image' else None,
                    type=m_type
                ))

    if not media_list:
        raise HTTPException(status_code=404, detail="No media links parsed")

    return InstagramResponse(
        media=media_list,
        media_count=len(media_list),
        requested_url=url,
        status="ok",
        username=extract_username(url)
    )

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
