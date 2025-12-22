import re
import httpx
import urllib.parse
import asyncio
from fastapi import FastAPI, Query, HTTPException
from bs4 import BeautifulSoup
from contextlib import asynccontextmanager

# --- CORE LOGIC ---

def _0xe12c(d, e, f):
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"
    h, i = alphabet[:e], alphabet[:f]
    d_list = list(d)[::-1]
    j = 0
    for index, char in enumerate(d_list):
        if char in h: j += h.find(char) * (e ** index)
    k = ""
    while j > 0:
        k = i[j % f] + k
        j = (j - (j % f)) // f
    return k or "0"

def decrypt_snapsave(h, u, n, t, e, r):
    decoded_str = ""
    i = 0
    while i < len(h):
        s = ""
        while i < len(h) and h[i] != n[e]:
            s += h[i]
            i += 1
        for j in range(len(n)): s = s.replace(n[j], str(j))
        try:
            decoded_str += chr(int(_0xe12c(s, e, 10)) - t)
        except: pass
        i += 1
    return urllib.parse.unquote(decoded_str)

# --- REUSABLE CLIENT (SPEED OPTIMIZATION) ---

class InstagramDownloader:
    def __init__(self):
        self.client = None

    async def start(self):
        # Optimized connection pool
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Origin": "https://snapsave.app",
                "Referer": "https://snapsave.app/"
            }
        )

    async def stop(self):
        await self.client.aclose()

    async def get_data(self, url: str):
        try:
            resp = await self.client.post("https://snapsave.app/action.php?lang=en", data={"url": url})
            if resp.status_code != 200: return None, "Provider error"

            match = re.search(r'\("([^"]+)",(\d+),"([^"]+)",(\d+),(\d+),(\d+)\)', resp.text)
            if not match: return None, "Link private or invalid"

            h, u, n, t, e, r = match.groups()
            html = re.search(r'\.innerHTML\s*=\s*"(.*?)";', decrypt_snapsave(h, int(u), n, int(t), int(e), int(r)), re.DOTALL)
            if not html: return None, "Decrypt error"
            
            soup = BeautifulSoup(html.group(1).replace('\\"', '"').replace('\\/', '/'), 'html.parser')
            media = []
            for item in soup.find_all('div', class_='download-items'):
                media.append({
                    "caption": "",
                    "media_url": item.find('a')['href'] if item.find('a') else "",
                    "source_type": "post",
                    "thumbnail_url": item.find('img')['src'] if item.find('img') else "",
                    "timestamp": "recent",
                    "type": "video" if "icon-dlvideo" in str(item) else "image"
                })
            return media, None
        except Exception as e:
            return None, str(e)

downloader = InstagramDownloader()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await downloader.start()
    yield
    await downloader.stop()

app = FastAPI(lifespan=lifespan)

@app.get("/download")
async def api_download(url: str = Query(...)):
    if "instagram.com" not in url:
        raise HTTPException(status_code=400, detail="Invalid URL")
    
    data, error = await downloader.get_data(url)
    if error: return {"status": "error", "message": error}

    username = "unknown"
    u_match = re.search(r"instagram\.com/([^/?#&]+)", url)
    if u_match: username = u_match.group(1)

    return {
        "media": data,
        "media_count": len(data),
        "requested_url": url,
        "source_of_data": "GetMedia",
        "status": "ok",
        "username": username
    }
