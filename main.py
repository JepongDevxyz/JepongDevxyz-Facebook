from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DownloadRequest(BaseModel):
    url: str
    quality: str = "best"

@app.get("/")
def read_root():
    return {"status": "online", "message": "Facebook Downloader API is running"}

@app.post("/api/download")
async def extract_video(payload: DownloadRequest):
    url = payload.url
    quality = payload.quality

    if not url or ("facebook.com" not in url and "fb.watch" not in url):
        return {
            "status": "error",
            "message": "Please provide a valid Facebook video URL."
        }

    # Format mapping
    if quality == "mp3":
        format_filter = "bestaudio/best"
    elif quality == "1080p":
        format_filter = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    elif quality == "720p":
        format_filter = "bestvideo[height<=720]+bestaudio/best[height<=720]"
    elif quality == "360p":
        format_filter = "bestvideo[height<=360]+bestaudio/best[height<=360]"
    elif quality == "worst":
        format_filter = "worstvideo+worstaudio/worst"
    else:
        format_filter = "bestvideo+bestaudio/best"

    ydl_opts = {
        'format': format_filter,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            duration_sec = info.get('duration') or 0
            minutes = int(duration_sec // 60)
            seconds = int(duration_sec % 60)
            formatted_duration = f"{minutes}:{seconds:02d} Min"

            download_url = info.get('url')
            if not download_url and info.get('formats'):
                download_url = info['formats'][-1].get('url')

            return {
                "status": "success",
                "video_info": {
                    "title": info.get('title') or info.get('fulltitle') or "Facebook Video",
                    "duration": formatted_duration,
                    "uploader": info.get('uploader') or "Facebook User",
                    "view_count": info.get('view_count') or 0,
                    "thumbnail": info.get('thumbnail')
                },
                "download_url": download_url or url
            }
    except Exception as e:
        return {
            "status": "error",
            "message": "Failed to extract video information: This video is private or not available for download."
        }
