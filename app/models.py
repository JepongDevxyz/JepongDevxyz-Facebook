from pydantic import BaseModel, HttpUrl
from typing import Optional, List, Dict, Any

class VideoRequest(BaseModel):
    url: str
    quality: Optional[str] = "best"

class VideoResponse(BaseModel):
    status: str
    video_info: Optional[Dict[str, Any]] = None
    download_url: Optional[str] = None
    available_formats: Optional[List[str]] = None
    message: Optional[str] = None
    error_code: Optional[str] = None
