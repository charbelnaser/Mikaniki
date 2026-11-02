import re

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from ..config import get_settings
from ..deps import get_current_user
from ..models import User
from ..schemas import EpaVersionOut, MakeOut, ModelOut, VinDecodeOut, VinPhotoOut
from ..services import catalog, epa, vin_photo
from ..services.diagnosis import ALLOWED_IMAGE_TYPES
from ..services.llm import LLMError

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # VINs never contain I, O, Q


@router.get("/makes", response_model=list[MakeOut])
async def makes():
    return await catalog.list_makes()


@router.get("/models", response_model=list[ModelOut])
async def models(make: str = Query(min_length=1, max_length=80), year: int = Query(ge=1950, le=2100)):
    return await catalog.list_models(make, year)


@router.get("/versions", response_model=list[EpaVersionOut])
async def versions(
    make: str = Query(min_length=1, max_length=80),
    model: str = Query(min_length=1, max_length=120),
    year: int = Query(ge=1984, le=2100),
):
    """Exact engine + gearbox versions from FuelEconomy.gov. Empty list if unknown or unreachable."""
    try:
        return await epa.list_options(year, make, model)
    except (httpx.HTTPError, ValueError):
        return []


@router.post("/vin-photo", response_model=VinPhotoOut)
async def vin_from_photo(image: UploadFile = File(...), user: User = Depends(get_current_user)):
    """Read the VIN from a photo of the registration card (auth required: each call costs an LLM request)."""
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG, WEBP or GIF images are supported")
    data = await image.read()
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Image too large (max {get_settings().max_upload_mb} MB)")
    try:
        vin = await vin_photo.read_vin(data, image.content_type)
    except LLMError:
        raise HTTPException(status_code=502, detail="The VIN reader is unavailable right now, please type the VIN")
    if not vin:
        raise HTTPException(status_code=422, detail="Could not read a VIN on this photo")
    return VinPhotoOut(vin=vin)


@router.get("/vin/{vin}", response_model=VinDecodeOut)
async def decode_vin(vin: str, user: User = Depends(get_current_user)):
    """Auth required: VINs vPIC cannot decode go to 17VIN, which is billed per result."""
    vin = vin.strip().upper()
    if not VIN_RE.match(vin):
        raise HTTPException(status_code=422, detail="A VIN has 17 characters (letters and digits, no I, O or Q)")
    try:
        result = await catalog.decode_vin(vin)
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="VIN service unavailable, please enter the car manually")
    if not result.make or not result.year:
        raise HTTPException(status_code=404, detail="VIN not recognised. Please choose your car from the catalog or enter it manually")
    return result
