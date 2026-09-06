import yt_dlp
import asyncio
from fastapi import HTTPException

class VideoService:
    @staticmethod
    async def get_video_info(url: str):
        ydl_opts = {
            'format': 'best[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'noplaylist': True,
        }
        
        def extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                    return {
                        "title": info.get("title"),
                        "duration": info.get("duration"),
                        "thumbnail": info.get("thumbnail"),
                        "uploader": info.get("uploader"),
                        "view_count": info.get("view_count", 0),
                        "formats": [f.get("format_note") for f in info.get("formats", []) if f.get("format_note")]
                    }
                except Exception as e:
                    raise HTTPException(status_code=400, detail=str(e))

        return await asyncio.to_thread(extract)

    @staticmethod
    async def get_download_url(url: str, quality: str = "best"):
        # Map quality options to yt-dlp format strings
        format_map = {
            "best": "best[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "worst": "worst",
            "360p": "best[height<=360][ext=mp4]/best[height<=360]",
            "720p": "best[height<=720][ext=mp4]/best[height<=720]",
            "1080p": "best[height<=1080][ext=mp4]/best[height<=1080]"
        }
        
        selected_format = format_map.get(quality, format_map["best"])
        
        ydl_opts = {
            'format': selected_format,
            'noplaylist': True,
        }

        def extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                    return {
                        "title": info.get("title"),
                        "duration": info.get("duration"),
                        "thumbnail": info.get("thumbnail"),
                        "uploader": info.get("uploader"),
                        "view_count": info.get("view_count", 0),
                        "url": info.get("url") # direct streaming/download url
                    }
                except Exception as e:
                    raise HTTPException(status_code=400, detail=str(e))

        return await asyncio.to_thread(extract)
