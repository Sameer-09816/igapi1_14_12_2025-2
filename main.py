import re
import httpx
import urllib.parse
from fastapi import FastAPI, HTTPException, Query
from bs4 import BeautifulSoup
from contextlib import asynccontextmanager

# --- OPTIMIZATION: Connection Pooling ---
# Reusing the same client across requests makes the API significantly faster.
state = {"client": None}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the global async client on startup
    state["client"] = httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://snapinsta.to/",
            "Origin": "https://snapinsta.to",
        },
        timeout=20.0,
        follow_redirects=True
    )
    yield
    # Clean up on shutdown
    await state["client"].aclose()

app = FastAPI(title="Instagram Downloader PRO", lifespan=lifespan)

# --- DE-OBFUSCATOR ---

def _0xe0c(d, e, f):
    charset = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"
    h, i = charset[0:e], charset[0:f]
    j = 0
    for index, char in enumerate(reversed(d)):
        if char in h: j += h.index(char) * (e ** index)
    if j == 0: return "0"
    k = ""
    while j > 0:
        k = i[j % f] + k
        j = (j - (j % f)) // f
    return k

def decode_snapinsta_video(js_content: str) -> str:
    try:
        matches = re.search(r'}\("([^"]+)",(\d+),"([^"]+)",(\d+),(\d+),(\d+)\)\)', js_content)
        if not matches: return js_content
        h, u, n, t, e, r_val = matches.groups()
        t, e, r, i = int(t), int(e), "", 0
        while i < len(h):
            s = ""
            while i < len(h) and h[i] != n[e]:
                s += h[i]
                i += 1
            for j in range(len(n)): s = s.replace(n[j], str(j))
            try: r += chr(int(_0xe0c(s, e, 10)) - t)
            except: pass
            i += 1
        decoded = urllib.parse.unquote(r)
        return decoded.replace('\\"', '"').replace('\\/', '/').replace('\\\\', '\\')
    except:
        return js_content

# --- HELPERS ---

def clean_url(url: str) -> str:
    if not url: return ""
    # Remove those pesky backslashes and extra quotes from the decoded JS
    url = re.sub(r'[\\\"\'\s]+', '', url)
    if url.startswith('//'): url = 'https:' + url
    return url

def extract_username(url: str) -> str:
    match = re.search(r"instagram\.com/([^/?#&]+)", url)
    if match:
        user = match.group(1)
        return user if user not in ["p", "reels", "reel", "tv"] else "instagram_user"
    return "instagram_user"

# --- CORE LOGIC ---

@app.get("/download")
async def download_api(url: str = Query(..., description="Instagram URL")):
    if "instagram.com" not in url:
        raise HTTPException(status_code=400, detail="Not a valid Instagram URL")

    client = state["client"]
    
    try:
        # 1. Verify Step
        v_res = await client.post("https://snapinsta.to/api/userverify", data={"url": url})
        token = v_res.json().get("token")
        if not token: raise Exception("Token generation failed")

        # 2. AJAX Search Step
        s_res = await client.post("https://snapinsta.to/api/ajaxSearch", data={
            "q": url, "t": "media", "v": "v2", "lang": "en", "cftoken": token
        })
        resp_json = s_res.json()
        raw_data = resp_json.get("data", "")

        # 3. Handle Video Obfuscation
        if "eval(function" in raw_data:
            raw_data = decode_snapinsta_video(raw_data)

        # 4. Parse HTML
        soup = BeautifulSoup(raw_data, "html.parser")
        media_results = []
        items = soup.find_all("div", class_="download-items") or soup.find_all("li")

        for item in items:
            btn = item.find("a", class_="abutton")
            if not btn: continue
            
            media_type = "video" if "video" in btn.get_text().lower() else "image"
            
            # Highest Quality Selection
            select = item.find("select")
            if select and select.find("option"):
                m_url = select.find("option")["value"]
            else:
                m_url = btn.get("href")

            # Thumbnail Selection
            img = item.find("img")
            t_url = ""
            if img:
                t_url = img.get("data-src") or img.get("src")
                if "loader.gif" in str(t_url): t_url = m_url

            media_results.append({
                "caption": "Instagram Content",
                "media_url": clean_url(m_url),
                "source_type": "post",
                "thumbnail_url": clean_url(t_url or m_url),
                "timestamp": "N/A",
                "type": media_type
            })

        return {
            "media": media_results,
            "media_count": len(media_results),
            "requested_url": url,
            "source_of_data": "GetMedia",
            "status": "ok",
            "username": extract_username(url)
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/health")
async def health():
    return {"status": "healthy"}
