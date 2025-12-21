import httpx
import re
import urllib.parse
from bs4 import BeautifulSoup
from cachetools import TTLCache

# Cache results for 5 minutes (300 seconds) to increase speed and reliability
cache = TTLCache(maxsize=100, ttl=300)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://snapinsta.to/",
    "Origin": "https://snapinsta.to",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

def decode_snap_data(h, u, n, t, e, r):
    try:
        delimiter = n[e]
        parts = h.split(delimiter)
        decoded_str = ""
        for s in parts:
            if not s: continue
            mapped_s = "".join([str(n.find(char)) for char in s])
            decoded_str += chr(int(mapped_s, e) - t)
        return urllib.parse.unquote(decoded_str)
    except:
        return None

def extract_params_and_decode(js_code: str):
    pattern = r'\("([^"]+)",\s*(\d+),\s*"([^"]+)",\s*(\d+),\s*(\d+),\s*(\d+)\)'
    match = re.search(pattern, js_code)
    if not match: return None
    return decode_snap_data(match.group(1), int(match.group(2)), match.group(3), int(match.group(4)), int(match.group(5)), int(match.group(6)))

async def get_ig_data(url: str, client: httpx.AsyncClient):
    # Check Cache first
    if url in cache:
        return cache[url]

    # Step 1: Verify
    v_res = await client.post("https://snapinsta.to/api/userverify", data={"url": url})
    token = v_res.json().get("token")
    if not token: return None

    # Step 2: Search
    payload = {"q": url, "t": "media", "v": "v2", "lang": "en", "cftoken": token}
    s_res = await client.post("https://snapinsta.to/api/ajaxSearch", data=payload)
    raw_data = s_res.json().get("data", "")

    # Step 3: Decode & Parse
    decoded_js = extract_params_and_decode(raw_data)
    if not decoded_js: return None

    html_match = re.search(r'innerHTML\s*=\s*"(.+?)";', decoded_js)
    clean_html = html_match.group(1).replace('\\"', '"').replace('\\/', '/') if html_match else decoded_js
    
    soup = BeautifulSoup(clean_html, "html.parser")
    media_list = []
    for item in soup.find_all("div", class_="download-items"):
        # Thumbnail Fix
        img = item.find("img")
        thumb = img.get("data-src") or img.get("src") if img else ""
        if thumb.startswith("/"): thumb = "https://snapinsta.to" + thumb

        # Media URL Fix
        link_tag = item.find("a", href=True)
        if not link_tag: continue
        media_url = link_tag["href"]
        if media_url.startswith("/"): media_url = "https://snapinsta.to" + media_url

        # Type Detection
        m_type = "video" if ("video" in link_tag.get("title", "").lower() or item.find("i", class_="icon-dlvideo")) else "image"

        media_list.append({
            "caption": f"Instagram {m_type} content",
            "media_url": media_url,
            "source_type": "post" if "/p/" in url else "reel",
            "thumbnail_url": thumb,
            "type": m_type
        })

    result = {
        "media": media_list,
        "media_count": len(media_list),
        "status": "ok"
    }
    
    # Store in cache
    if media_list:
        cache[url] = result
        
    return result
