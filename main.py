from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
import yt_dlp
import os
import requests
from upstash_redis import Redis

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Upstash Redis Connection (Siguraduhing naka-set ang env variables sa Render)
redis_url = os.getenv("UPSTASH_REDIS_REST_URL")
redis_token = os.getenv("UPSTASH_REDIS_REST_TOKEN")
redis = Redis(url=redis_url, token=redis_token) if redis_url and redis_token else None

class DownloadRequest(BaseModel):
    url: str
    quality: str = "best"

@app.get("/", response_class=HTMLResponse)
def read_index():
    if os.path.exists("public/index.html"):
        with open("public/index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "Backend is running! Please place index.html inside the public folder."

@app.get("/api/counter")
def get_counter():
    try:
        count = redis.get("total_downloads") if redis else 0
        return {"status": "success", "count": int(count) if count else 0}
    except Exception as e:
        return {"status": "success", "count": 0}

@app.post("/api/counter")
def increment_counter():
    try:
        count = redis.incr("total_downloads") if redis else 1
        return {"status": "success", "count": int(count)}
    except Exception as e:
        return {"status": "success", "count": 1}

@app.post("/api/download")
def download_video(req: DownloadRequest):
    ydl_opts = {'format': 'best'}
    if req.quality == '1080p':
        ydl_opts['format'] = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
    elif req.quality == '720p':
        ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
    elif req.quality == '360p':
        ydl_opts['format'] = 'bestvideo[height<=360]+bestaudio/best[height<=360]'
    elif req.quality == 'worst':
        ydl_opts['format'] = 'worst'
    elif req.quality == 'mp3':
        ydl_opts['format'] = 'bestaudio/best'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)
            download_url = info.get('url')
            
            return {
                "status": "success",
                "download_url": download_url,
                "video_info": {
                    "title": info.get('title'),
                    "duration": info.get('duration_string'),
                    "uploader": info.get('uploader'),
                    "view_count": info.get('view_count'),
                    "thumbnail": info.get('thumbnail')
                }
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/proxy-download")
def proxy_download(url: str, filename: str = "video.mp4"):
    try:
        resp = requests.get(url, stream=True, timeout=30)
        
        def iterfile():
            for chunk in resp.iter_content(chunk_size=1024*1024):
                if chunk:
                    yield chunk

        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
        return StreamingResponse(iterfile(), headers=headers, media_type=resp.headers.get("content-type", "video/mp4"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
