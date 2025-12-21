from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
from scraper import get_ig_data, HEADERS
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup: Create a global httpx client for connection pooling
    app.state.client = httpx.AsyncClient(headers=HEADERS, timeout=30.0, follow_redirects=True)
    yield
    # Teardown: Close the client
    await app.state.client.aclose()

app = FastAPI(title="Pro IG Downloader API", lifespan=lifespan)

# Enable CORS for your frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "IG Downloader API is running"}

@app.get("/api/download")
async def download(url: str = Query(..., example="https://www.instagram.com/p/DSXggmwEoKg/")):
    data = await get_ig_data(url, app.state.client)
    if not data:
        raise HTTPException(status_code=400, detail="Failed to fetch media. Verify the URL is public.")
    
    data["requested_url"] = url
    return data
