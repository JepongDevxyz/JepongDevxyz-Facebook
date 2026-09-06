import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from upstash_redis import Redis
from app.models import VideoRequest, VideoResponse
from app.services.video_service import VideoService

app = FastAPI(title="Facebook Video Downloader API", version="1.0.0")

# Initialize Upstash Redis connection galing sa environment variables
redis_url = os.getenv("UPSTASH_REDIS_REST_URL", "")
redis_token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
redis_client = Redis(url=redis_url, token=redis_token) if redis_url and redis_token else None

# Mount static folder kung saan nakalagay ang frontend web interface mo
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"message": "API is running. Please check /docs for documentation."}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/api/counter")
async def get_counter():
    if not redis_client:
        return {"status": "success", "count": 0}
    try:
        count = redis_client.get("total_downloads") or 0
        return {"status": "success", "count": int(count)}
    except Exception:
        return {"status": "success", "count": 0}

@app.post("/api/counter")
async def increment_counter():
    if not redis_client:
        return {"status": "success", "count": 0}
    try:
        count = redis_client.incr("total_downloads")
        return {"status": "success", "count": int(count)}
    except Exception:
        return {"status": "success", "count": 0}

@app.post("/info", response_model=VideoResponse)
async def video_info(data: VideoRequest):
    try:
        info = await VideoService.get_video_info(data.url)
        return {
            "status": "success",
            "video_info": info,
            "available_formats": ["360p", "720p", "1080p", "best", "worst"]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/download", response_model=VideoResponse)
async def download_video(data: VideoRequest):
    try:
        result = await VideoService.get_download_url(data.url, data.quality)
        download_link = result.pop("url", None)
        return {
            "status": "success",
            "video_info": result,
            "download_url": download_link,
            "available_formats": ["360p", "720p", "1080p", "best", "worst"]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "error_code": "INVALID_REQUEST"
        }

@app.get("/qualities")
async def get_qualities():
    return {
        "qualities": ["best", "worst", "360p", "720p", "1080p"]
    }
