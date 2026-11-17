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
    is_youtube = "youtube.com" in req.url or "youtu.be" in req.url
    ydl_opts = {'format': 'best'}
    if is_youtube:
        # YouTube: android player client lang ang nakakakita ng
        # single-file MP4 (format 18, 360p). Ang default web client
        # ay DASH-only na (walang combined format) kaya "Requested
        # format is not available" lang ang error. Tandaan: 360p lang
        # ang combined MP4 na binibigay ng YouTube dito — walang
        # 720p/1080p single-file; yun ay DASH at kailangan ng merge.
        ydl_opts['extractor_args'] = {'youtube': {'player_client': ['android']}}
        # YouTube: single-file MP4 lang ang pipiliin. Ang merged DASH
        # formats (bestvideo+bestaudio) ay walang iisang download URL,
        # kaya download_url: null ang bumabalik. FB links: walang
        # nagbabago — dating format mapping pa rin ang gamit sa baba.
        if req.quality == '1080p':
            ydl_opts['format'] = 'best[height<=1080][ext=mp4]/best[height<=1080][ext=mp4]/best'
        elif req.quality == '720p':
            ydl_opts['format'] = 'best[height<=720][ext=mp4]/best[height<=720][ext=mp4]/best'
        elif req.quality == '360p':
            ydl_opts['format'] = 'best[height<=360][ext=mp4]/best[height<=360][ext=mp4]/best'
        elif req.quality == 'worst':
            ydl_opts['format'] = 'worst[ext=mp4]/worst'
        elif req.quality == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
        else:  # best
            ydl_opts['format'] = 'best[ext=mp4]/best[ext=mp4]/best'
    elif req.quality == '1080p':
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

# Anong resolution ang TUNAY na available para sa link na ito?
# Hindi cap ang binabalik — yung totoong resolution ng file na
# mada-download. Hal. YouTube: tanging format 18 (360p) lang ang
# combined MP4, kaya "360p" lang ang lalabas kahit 1080p ang pinili
# mo dati (360p file pa rin ang bumabalik nun — misleading).
#   YouTube  -> combined mp4 lang (may video AT audio sa iisang file)
#   Facebook -> kahit anong video format (merged ang download doon)
# Ang "best" ay available kung may kahit anong video na mada-download.
# Ang 1080p/720p/360p ay available lang kung yung pinakamataas na
# format na pasok sa cap ay EXACTLY yung cap na yun.
@app.post("/api/formats")
def list_formats(req: DownloadRequest):
    is_youtube = "youtube.com" in req.url or "youtu.be" in req.url
    ydl_opts = {'format': 'best', 'skip_download': True}
    if is_youtube:
        ydl_opts['extractor_args'] = {'youtube': {'player_client': ['android']}}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    heights = set()
    has_video = False
    for f in info.get('formats') or []:
        vcodec = f.get('vcodec')
        acodec = f.get('acodec')
        if not vcodec or vcodec == 'none':
            continue
        has_video = True
        if is_youtube:
            # Single-file MP4 lang ang may direktang download URL.
            if f.get('ext') != 'mp4' or not acodec or acodec == 'none':
                continue
        h = f.get('height')
        if h:
            heights.add(int(h))

    available = []
    if has_video:
        available.append('best')
    for cap in (1080, 720, 360):
        below = [h for h in heights if h <= cap]
        if below and max(below) == cap:
            available.append(f'{cap}p')
    best_height = max(heights) if heights else None
    return {
        "status": "success",
        "platform": "youtube" if is_youtube else "facebook",
        "title": info.get('title'),
        "available": available,
        "best_height": best_height,
        "video_info": {
            "title": info.get('title'),
            "duration": info.get('duration_string'),
            "uploader": info.get('uploader'),
            "view_count": info.get('view_count'),
            "thumbnail": info.get('thumbnail')
        }
    }

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
