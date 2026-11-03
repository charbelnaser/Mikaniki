from dataclasses import asdict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_current_user
from ..models import User
from ..schemas import PartPhotoOut, VideoOut, WebImageOut
from ..services import images, media

# Auth required so the API is not an open proxy to Wikimedia / YouTube quota
router = APIRouter(prefix="/api/media", tags=["media"], dependencies=[Depends(get_current_user)])


@router.get("/part-photo", response_model=PartPhotoOut)
async def part_photo(q: str = Query(min_length=2, max_length=80)):
    try:
        photo = await media.part_photo(q)
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Photo service unavailable")
    if photo is None:
        raise HTTPException(status_code=404, detail="No photo found")
    return PartPhotoOut(**asdict(photo))


@router.get("/video", response_model=VideoOut | None)
async def video(q: str = Query(min_length=3, max_length=150)):
    """Top YouTube video, or null when no API key is configured / nothing found (the app then links to a search)."""
    try:
        found = await media.repair_video(q)
    except httpx.HTTPError:
        return None
    return VideoOut(**asdict(found)) if found else None


@router.get("/images", response_model=list[WebImageOut])
async def web_images(q: str = Query(min_length=3, max_length=150)):
    """Web photos for a query ("2016 Toyota Corolla ignition coil location"); [] when not configured or down."""
    try:
        found = await images.search(q, count=4)
    except httpx.HTTPError:
        return []
    return [WebImageOut(**asdict(i)) for i in found]
