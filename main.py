from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from starlette.background import BackgroundTask  # BackgroundTask is in starlette, NOT fastapi.background (fastapi.background has only BackgroundTasks) — maling import dito = crash ang buong app sa startup, lahat ng /api/* 500
from pydantic import BaseModel
import yt_dlp
import os
import re
import shutil
import subprocess
import tempfile
import time
import math
import urllib.parse
import requests
from upstash_redis import Redis

# v9: ang raw yt-dlp error (bot check + wiki links) ay hindi na
# ipinapakita sa user — maikling Tagalog message na lang.
BOT_MSG = "Na-block ng YouTube ang server ngayon (bot check). Subukan ulit mamaya, o 360p/MP3 muna."
def friendly_err(e):
    msg = str(e)
    low = msg.lower()
    if 'sign in to confirm' in low or 'not a bot' in low:
        return BOT_MSG
    if 'requested format is not available' in low:
        return "Hindi makuha ang video na ito ngayon. Subukan ang ibang quality o subukan ulit mamaya."
    if 'video unavailable' in low or 'private video' in low:
        return "Hindi available ang video na ito (private o tinanggal)."
    return msg

def _cap_dim(q):
    # v10: '1080p' -> 1920. Ang cap ay ang MALAKING dimension (16:9),
    # para gumana sa portrait (1080x1920) at landscape (1920x1080).
    m = re.fullmatch(r'(\d+)p', q or '')
    n = min(int(m.group(1)), 4320) if m else 4320
    return math.ceil(n * 16 / 9)

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
def get_counter(platform: str = ""):
    # v11: per-platform counter — 'reddit' lang ang may sariling key
    # ("counter:reddit"); ang default ("total_downloads") ay ang
    # Facebook counter pa rin (hindi ni-reset ang bilang).
    # TANDAAN (2026-11-18): ang live /api/counter ay HINDI ito ang
    # nagsisilbi — Vercel filesystem routing: api/counter.js (standalone,
    # key "global_downloads") ang sumasalo sa /api/counter, kaya ang
    # platform support ay nasa api/counter.js din. Itong FastAPI counter
    # ay fallback lang at hindi naaabot sa live.
    key = "counter:reddit" if platform == "reddit" else "total_downloads"
    try:
        count = redis.get(key) if redis else 0
        return {"status": "success", "count": int(count) if count else 0}
    except Exception as e:
        return {"status": "success", "count": 0}

@app.post("/api/counter")
def increment_counter(platform: str = ""):
    key = "counter:reddit" if platform == "reddit" else "total_downloads"
    try:
        count = redis.incr(key) if redis else 1
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
        # v9: kahit anong '{height}p' (1440p/480p/240p/144p kasama) —
        # parse lang ang numero, hindi na hardcoded na listahan.
        _m = re.fullmatch(r'(\d+)p', req.quality or '')
        if _m:
            _d = _cap_dim(req.quality)
            ydl_opts['format'] = f'best[height<={_d}][width<={_d}][ext=mp4]/best[height<={_d}][width<={_d}][ext=mp4]/best'
        elif req.quality == 'worst':
            ydl_opts['format'] = 'worst[ext=mp4]/worst'
        elif req.quality == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
        else:  # best
            ydl_opts['format'] = 'best[ext=mp4]/best[ext=mp4]/best'
    elif req.quality == 'worst':
        ydl_opts['format'] = 'worst'
    elif req.quality == 'mp3':
        ydl_opts['format'] = 'bestaudio/best'
    else:
        # v9: kahit anong '{height}p' para sa Facebook din.
        _m = re.fullmatch(r'(\d+)p', req.quality or '')
        if _m:
            _d = _cap_dim(req.quality)
            ydl_opts['format'] = f'bestvideo[height<={_d}][width<={_d}]+bestaudio/best[height<={_d}][width<={_d}]'
        else:
            ydl_opts['format'] = 'best'

    # v9: YouTube = 2 attempts (pabugso-bugso ang bot check).
    info = None
    last_err = None
    for _ in range(2 if is_youtube else 1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(req.url, download=False)
            break
        except Exception as e:
            last_err = e
            time.sleep(1)
    if info is None:
        raise HTTPException(status_code=400, detail=friendly_err(last_err))
    download_url = info.get('url')
    if not download_url:
        # v10: dati, success + null URL ang bumabalik pag multi-format
        # ang selection (hal. FB 1080p) — sirang download button yun.
        # Ngayon, malinaw na 400 na lang.
        raise HTTPException(status_code=400, detail="Hindi makuha ang download link ng video na ito. Subukan ang ibang quality o subukan ulit mamaya.")

    try:
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
        raise HTTPException(status_code=400, detail=friendly_err(e))

# Anong resolution ang TUNAY na available para sa link na ito?
# Hindi cap ang binabalik — yung totoong resolution ng file na
# mada-download. Hal. YouTube: tanging format 18 (360p) lang ang
# combined MP4, kaya "360p" lang ang lalabas kahit 1080p ang pinili
# mo dati (360p file pa rin ang bumabalik nun — misleading).
#   YouTube  -> combined mp4 lang (may video AT audio sa iisang file)
#   Facebook -> kahit anong video format (merged ang download doon)
# v9: LAHAT ng tunay na height ang lalabas (1440p/480p/240p/144p
# kasama) — hindi lang yung 5 caps. Kung ano ang available, yun
# din ang ipapakita sa picker at mada-download (tulad ng YouTube).
# Ang "best" ay available kung may kahit anong video na mada-download.
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
    # v8: ang web attempt ay gumagamit ng PAREHONG format selector
    # gaya ng merge endpoint ('best' lang dati) — sa live test, ang
    # merge extract ay gumagana 5/5 habang ang formats extract na
    # 'best' lang ay bumabagsak 3/3, kaya pareho na sila ngayon.
    # Dalawang beses susubukan ang web bago mag-android fallback.
    # v9: android, 3 attempts — pabugso-bugso ang bot check, kaya
    # inuulit (minsan gumagana sa 2nd/3rd try).
    merge_fmt = 'bestvideo[height<=4320][ext=mp4]+bestaudio[ext=m4a]/best[height<=4320][ext=mp4]/best[height<=4320]'
    clients = [
        {'format': merge_fmt, 'skip_download': True},
        {'format': merge_fmt, 'skip_download': True},
    ]
    if is_youtube:
        android = {'format': 'best', 'skip_download': True, 'extractor_args': {'youtube': {'player_client': ['android']}}}
        clients.extend([android, android, android])
    else:
        clients.append({'format': 'best', 'skip_download': True})
    for extra in clients:
        ydl_opts = {'format': 'best', **extra}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(req.url, download=False)
            break
        except Exception as e:
            last_err = e
            time.sleep(1)
    if info is None:
        raise HTTPException(status_code=400, detail=friendly_err(last_err))

    video_heights = set()
    combined_heights = set()
    has_video = False
    for f in info.get('formats') or []:
        vcodec = f.get('vcodec')
        acodec = f.get('acodec')
        if not vcodec or vcodec == 'none':
            continue
        # v7: sa YouTube, mp4 video lang ang binibilang — yun lang ang
        # kayang i-merge ng server bilang MP4 (ang webm/vp9/opus ay
        # hindi kayang i-mux ng ffmpeg 4.2 sa MP4). Sa Facebook, mp4
        # naman lahat, kaya walang filter doon.
        if is_youtube and f.get('ext') != 'mp4':
            continue
        has_video = True
        # v10: ang label ay ang MALIIT na dimension (tulad ng YouTube:
        # 1080x1920 portrait = '1080p', 1920x1080 landscape = '1080p').
        w = f.get('width')
        h = f.get('height')
        m = min(w, h) if w and h else (h or w)
        if m and m <= 4320:  # hanggang 8K (v5) — kung available
            video_heights.add(int(m))
            if f.get('ext') == 'mp4' and acodec and acodec != 'none':
                combined_heights.add(int(m))

    available = []
    merged_qualities = []
    if has_video:
        available.append('best')
        best_video = max(video_heights) if video_heights else None
        best_combined = max(combined_heights) if combined_heights else None
        if best_video and best_video != best_combined:
            # v10: pati Facebook — ang 'best' ng FB ay 720p lang pala, ang
            # 1080p ay hiwalay na video+audio kaya kailangan ng merge.
            merged_qualities.append('best')
    for h in sorted(video_heights, reverse=True):
        available.append(f'{h}p')
        cbelow = [c for c in combined_heights if c <= h]
        if not cbelow or max(cbelow) != h:
            merged_qualities.append(f'{h}p')
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
# v11: Reddit — hindi na pwede ang yt-dlp (ngayon, kailangan na ng
# login: "Account authentication is required"), kaya FreeApi.Pro
# (no-key, napatunayan) ang resolver: videoUrl -> DASH mp4 +
# DASH_AUDIO_128.mp4, tapos i-merge ng ffmpeg. Walang tunog ang
# video-only link, kaya kailangan ang merge — tulad ng YouTube.
def _merge_reddit(url, ffmpeg_path):
    sub = ''
    pid = ''
    m = re.search(r'reddit\.com/r/([^/]+)/comments/([^/\s?#]+)', url)
    if m:
        sub, pid = m.group(1), m.group(2)
    else:
        m2 = re.search(r'redd\.it/([A-Za-z0-9]+)', url)
        if m2:
            pid = m2.group(1)
    # v11: FreeApi.Pro minsan bumabagsak (rapidsave timeout + reddit-json
    # 403 — pabugso-bugso), kaya 2 attempts na may 15s timeout bawat isa
    # (kapag healthy, 1-2s lang ang sagot; ang 15s ay para hindi maubos
    # ang 60s serverless limit sa dalawang bagsak na attempt).
    data = None
    video_url = ''
    for attempt in range(2):
        try:
            r = requests.get('https://freeapi.pro/api/alldl', params={'url': url},
                             timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            data = r.json()
        except Exception:
            data = None
        media = (data or {}).get('mediaInfo') or {}
        video_url = media.get('videoUrl') or ''
        if video_url:
            break
        if attempt == 0:
            time.sleep(2)
    if not data:
        raise HTTPException(status_code=400, detail="Hindi makontak ang Reddit resolver. Subukan ulit mamaya.")
    dash = ''
    if video_url:
        qs = urllib.parse.urlparse(video_url).query
        vv = urllib.parse.parse_qs(qs).get('video_url') or []
        dash = vv[0] if vv else ''
    if not dash:
        raise HTTPException(status_code=400, detail="Hindi makuha ang video ng Reddit post na ito. Siguraduhing public video post ang link.")
    parsed = urllib.parse.urlparse(dash)
    base_path = parsed.path.rsplit('/', 1)[0]
    audio_url = f"{parsed.scheme}://{parsed.netloc}{base_path}/DASH_AUDIO_128.mp4"
    tmpdir = tempfile.mkdtemp(prefix="alldl-reddit-")
    try:
        vpath = os.path.join(tmpdir, 'video.mp4')
        apath = os.path.join(tmpdir, 'audio.mp4')
        total = 0
        with requests.get(dash, stream=True, timeout=60, headers={'User-Agent': 'Mozilla/5.0'}) as resp:
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Hindi ma-download ang Reddit video. Subukan ulit mamaya.")
            with open(vpath, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
                        if total > 400_000_000:
                            raise HTTPException(status_code=400, detail="Masyadong malaki ang file para i-merge sa free server (humigit ~400MB).")
        if os.path.getsize(vpath) < 10000:
            raise HTTPException(status_code=400, detail="Hindi makuha ang video ng Reddit post na ito.")
        # Audio: kung walang audio ang post (o 404 ang DASH_AUDIO),
        # video-only pa rin ang ibalik — hindi error.
        has_audio = False
        try:
            with requests.get(audio_url, stream=True, timeout=60, headers={'User-Agent': 'Mozilla/5.0'}) as resp:
                if resp.status_code == 200:
                    with open(apath, 'wb') as f:
                        for chunk in resp.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    has_audio = os.path.getsize(apath) >= 1000
        except Exception:
            has_audio = False
        out = os.path.join(tmpdir, 'merged.mp4')
        if has_audio:
            proc = subprocess.run([ffmpeg_path, '-y', '-i', vpath, '-i', apath,
                                   '-c:v', 'copy', '-c:a', 'aac', '-movflags', '+faststart', out],
                                  capture_output=True, timeout=300)
            if proc.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 10000:
                raise HTTPException(status_code=400, detail="Hindi ma-merge ang Reddit video. Subukan ulit mamaya.")
        else:
            shutil.copyfile(vpath, out)
        name = f"reddit-{sub}-{pid}" if pid else "reddit-video"
        name = re.sub(r'[\\/:*?"<>|]', '', name).strip() or 'reddit-video'
        return FileResponse(
            out,
            media_type='video/mp4',
            filename=f"{name}.mp4",
            background=BackgroundTask(shutil.rmtree, tmpdir, True),
        )
    except HTTPException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=friendly_err(e))

def _download_x(url):
    # v12: X (Twitter) — FreeApi.Pro resolve (platform 'Twitter'),
    # direktang MP4 na isang file lang (may audio na — hindi tulad ng
    # Reddit na hiwalay ang video at audio), kaya WALANG merge at
    # WALANG ffmpeg. 2 attempts, 15s timeout bawat isa (kapag healthy,
    # 1-2s lang ang sagot; napatunayan: 9.2MB, 93.6s, 720x720 + aac).
    user = ''
    sid = ''
    m = re.search(r'(?:x\.com|twitter\.com)/([^/\s?#]+)/status/(\d+)', url)
    if m:
        user, sid = m.group(1), m.group(2)
    data = None
    video_url = ''
    for attempt in range(2):
        try:
            r = requests.get('https://freeapi.pro/api/alldl', params={'url': url},
                             timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            data = r.json()
        except Exception:
            data = None
        media = (data or {}).get('mediaInfo') or {}
        video_url = media.get('videoUrl') or ''
        if video_url:
            break
        if attempt == 0:
            time.sleep(2)
    if not data:
        raise HTTPException(status_code=400, detail="Hindi makontak ang X resolver. Subukan ulit mamaya.")
    if not video_url:
        raise HTTPException(status_code=400, detail="Hindi makuha ang video ng X post na ito. Siguraduhing public video post ang link.")
    tmpdir = tempfile.mkdtemp(prefix="alldl-x-")
    try:
        vpath = os.path.join(tmpdir, 'video.mp4')
        total = 0
        with requests.get(video_url, stream=True, timeout=120, headers={'User-Agent': 'Mozilla/5.0'}) as resp:
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Hindi ma-download ang X video. Subukan ulit mamaya.")
            with open(vpath, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
                        if total > 400_000_000:
                            raise HTTPException(status_code=400, detail="Masyadong malaki ang file para i-download sa free server (humigit ~400MB).")
        if os.path.getsize(vpath) < 10000:
            raise HTTPException(status_code=400, detail="Hindi makuha ang video ng X post na ito.")
        name = f"x-{user}-{sid}" if sid else "x-video"
        name = re.sub(r'[\\/:*?"<>|]', '', name).strip() or 'x-video'
        return FileResponse(
            vpath,
            media_type='video/mp4',
            filename=f"{name}.mp4",
            background=BackgroundTask(shutil.rmtree, tmpdir, True),
        )
    except HTTPException:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=friendly_err(e))

@app.post("/api/download-merged")
def download_merged(req: DownloadRequest):
    # v12: X — direct MP4 (may audio na), walang merge, walang ffmpeg —
    # kaya bago pa ang ffmpeg check ang ruta nito.
    if "x.com" in req.url or "twitter.com" in req.url:
        return _download_x(req.url)
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
    # v11: Reddit — FreeApi.Pro + ffmpeg merge (hindi yt-dlp; kailangan
    # na ng login ang yt-dlp Reddit extractor).
    if "reddit.com" in req.url or "redd.it" in req.url:
        return _merge_reddit(req.url, ffmpeg_path)
    is_youtube = "youtube.com" in req.url or "youtu.be" in req.url
    q = req.quality or 'best'
    # v7: ang AUDIO ay laging m4a/aac lang — ang bundled ffmpeg 4.2 ay
    # HINDI kayang i-mux ang opus audio sa MP4 (yun ang "Postprocessing"
    # error ng v6: bestaudio ang pinili ay opus 251). Ang video ay
    # bestvideo pa rin (av1 o avc1 — parehong kayang i-mux ng ffmpeg
    # 4.2 sa MP4, napatunayan sa local test gamit ang mismong 4.2.2
    # binary). Pag walang mp4 video sa cap, combined mp4 ang fallback.
    # v9: kahit anong '{height}p' (1440p/480p/240p/144p kasama) —
    # parse lang ang numero, hindi na hardcoded na listahan.
    # v10: D-cap (malaking dimension) + audio fallback: m4a muna, tapos
    # kahit anong audio (para sa Facebook na hindi m4a ang audio).
    _d = _cap_dim(q)
    fmt = (f'bestvideo[height<={_d}][width<={_d}][ext=mp4]+bestaudio[ext=m4a]'
           f'/bestvideo[height<={_d}][width<={_d}][ext=mp4]+bestaudio'
           f'/best[height<={_d}][width<={_d}][ext=mp4]/best[height<={_d}][width<={_d}]')

    # 1) Alamin kung gumagana ang web client (at gaano kahaba/kalaki ang
    #    video) bago mag-download. Pag bot-blocked, android fallback.
    # v9: android, 3 attempts — pabugso-bugso ang bot check.
    clients = [{}]
    if is_youtube:
        android = {'extractor_args': {'youtube': {'player_client': ['android']}}}
        clients.extend([android, android, android])
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
            time.sleep(1)
    if info is None:
        raise HTTPException(status_code=400, detail=friendly_err(last_err))
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
        raise HTTPException(status_code=400, detail=friendly_err(e))

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
