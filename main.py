from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from starlette.background import BackgroundTask  # BackgroundTask is in starlette, NOT fastapi.background (fastapi.background has only BackgroundTasks) — maling import dito = crash ang buong app sa startup, lahat ng /api/* 500
from pydantic import BaseModel
import yt_dlp
import os
import re
import shutil
import tempfile
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
# v4: para sa YouTube, web client na ang gamit (DASH heights — yun ang
# tunay na resolution; hanggang 8K (4320p) kung available — v5).
# `merged_qualities` = yung qualities na kailangan ng server-side merge
# (hiwalay ang video at audio); yung wala dito, direktang link lang.
@app.post("/api/formats")
def list_formats(req: DownloadRequest):
    is_youtube = "youtube.com" in req.url or "youtu.be" in req.url
    info = None
    last_err = None
    # YouTube: web client muna (DASH heights); pag bot-blocked,
    # android fallback (single-file 360p lang ang makikita).
    clients = [{}]
    if is_youtube:
        clients.append({'extractor_args': {'youtube': {'player_client': ['android']}}})
    for extra in clients:
        ydl_opts = {'format': 'best', 'skip_download': True, **extra}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(req.url, download=False)
            break
        except Exception as e:
            last_err = e
    if info is None:
        raise HTTPException(status_code=400, detail=str(last_err))

    video_heights = set()
    combined_heights = set()
    has_video = False
    for f in info.get('formats') or []:
        vcodec = f.get('vcodec')
        acodec = f.get('acodec')
        if not vcodec or vcodec == 'none':
            continue
        has_video = True
        h = f.get('height')
        if h and h <= 4320:  # hanggang 8K (v5) — kung available
            video_heights.add(int(h))
            if f.get('ext') == 'mp4' and acodec and acodec != 'none':
                combined_heights.add(int(h))

    available = []
    merged_qualities = []
    if has_video:
        available.append('best')
        best_video = max(video_heights) if video_heights else None
        best_combined = max(combined_heights) if combined_heights else None
        if is_youtube and best_video and best_video != best_combined:
            merged_qualities.append('best')
    for cap in (4320, 2160, 1080, 720, 360):
        below = [h for h in video_heights if h <= cap]
        if below and max(below) == cap:
            available.append(f'{cap}p')
            if is_youtube:
                cbelow = [h for h in combined_heights if h <= cap]
                if not cbelow or max(cbelow) != cap:
                    merged_qualities.append(f'{cap}p')
    best_height = max(video_heights) if video_heights else None
    return {
        "status": "success",
        "platform": "youtube" if is_youtube else "facebook",
        "title": info.get('title'),
        "available": available,
        "merged_qualities": merged_qualities,
        "best_height": best_height,
        "video_info": {
            "title": info.get('title'),
            "duration": info.get('duration_string'),
            "uploader": info.get('uploader'),
            "view_count": info.get('view_count'),
            "thumbnail": info.get('thumbnail')
        }
    }

# Tunay na resolution: i-download ang video + audio, i-merge gamit ang
# ffmpeg, at i-stream ang buong MP4 file. Para ito sa mga quality na
# walang single-file MP4 (hal. YouTube 720p/1080p/4K/8K — DASH lang sila).
# Hanggang 8K (4320p) kung available (v5), 15 minuto lang ang video, at
# ~400MB lang ang file (free server limits — pag lumampas, malinaw na
# 400 ang ibabalik, hindi tahimik na fail). Kung walang ffmpeg sa
# server, malinaw na 400 rin ang ibabalik.
# v6: walang ffmpeg ang Vercel serverless — kaya imageio-ffmpeg ang
# gamit (pip package na may kasamang static ffmpeg binary) pag walang
# system ffmpeg.
# Kung bot-blocked ang web client, android fallback: direktang link ng
# single-file 360p ang ibabalik bilang JSON (hindi merge).
@app.post("/api/download-merged")
def download_merged(req: DownloadRequest):
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        try:
            import imageio_ffmpeg
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg_path = None
    if not ffmpeg_path:
        raise HTTPException(
            status_code=400,
            detail="Merge not available: ffmpeg is not installed on this server.",
        )
    is_youtube = "youtube.com" in req.url or "youtu.be" in req.url
    q = req.quality or 'best'
    if q == '4320p':
        fmt = 'bestvideo[height<=4320]+bestaudio/best[height<=4320]'
    elif q == '2160p':
        fmt = 'bestvideo[height<=2160]+bestaudio/best[height<=2160]'
    elif q == '1080p':
        fmt = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
    elif q == '720p':
        fmt = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
    elif q == '360p':
        fmt = 'bestvideo[height<=360]+bestaudio/best[height<=360]'
    else:  # best — hanggang 8K kung available
        fmt = 'bestvideo[height<=4320]+bestaudio/best[height<=4320]'

    # 1) Alamin kung gumagana ang web client (at gaano kahaba/kalaki ang
    #    video) bago mag-download. Pag bot-blocked, android fallback.
    clients = [{}]
    if is_youtube:
        clients.append({'extractor_args': {'youtube': {'player_client': ['android']}}})
    info = None
    used_android = False
    last_err = None
    for extra in clients:
        try:
            with yt_dlp.YoutubeDL({'format': fmt, 'skip_download': True, **extra}) as ydl:
                info = ydl.extract_info(req.url, download=False)
            used_android = bool(extra)
            break
        except Exception as e:
            last_err = e
    if info is None:
        raise HTTPException(status_code=400, detail=str(last_err))
    duration = info.get('duration') or 0
    if duration > 900:
        raise HTTPException(
            status_code=400,
            detail="Masyadong mahaba ang video para i-merge (higit 15 minuto). Subukan ang 360p o MP3.",
        )
    if not used_android:
        # Tantya ng laki ng video+audio na mada-download (free server
        # lang ito — pag ~400MB pataas, baka hindi kayanin ng box).
        total_size = 0
        sized = False
        for f in info.get('requested_formats') or []:
            sz = f.get('filesize') or f.get('filesize_approx')
            if sz:
                total_size += int(sz)
                sized = True
        if sized and total_size > 400_000_000:
            raise HTTPException(
                status_code=400,
                detail="Masyadong malaki ang file para i-merge sa free server (humigit ~400MB). Subukan ang mas mababang resolution.",
            )
    if used_android:
        # Single-file lang ang kaya — ibalik ang direktang link.
        url = info.get('url')
        if not url:
            raise HTTPException(status_code=400, detail="Hindi makuha ang video na ito.")
        return {
            "status": "success",
            "download_url": url,
            "merged": False,
            "video_info": {
                "title": info.get('title'),
                "duration": info.get('duration_string'),
                "uploader": info.get('uploader'),
                "view_count": info.get('view_count'),
                "thumbnail": info.get('thumbnail')
            }
        }

    # 2) Download + merge sa temp dir, tapos i-stream ang file.
    tmpdir = tempfile.mkdtemp(prefix="alldl-merge-")
    try:
        ydl_opts = {
            'format': fmt,
            'outtmpl': os.path.join(tmpdir, 'video.%(ext)s'),
            'merge_output_format': 'mp4',
            'ffmpeg_location': ffmpeg_path,
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(req.url, download=True)
        merged = None
        for name in os.listdir(tmpdir):
            if name.endswith('.mp4'):
                merged = os.path.join(tmpdir, name)
                break
        if not merged:
            raise HTTPException(status_code=400, detail="Hindi nabuo ang merged video.")
        title = re.sub(r'[\\/:*?"<>|]', '', info.get('title') or 'video').strip() or 'video'
        return FileResponse(
            merged,
            media_type='video/mp4',
            filename=f"{title}.mp4",
            background=BackgroundTask(shutil.rmtree, tmpdir, True),
        )
    except HTTPException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
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
