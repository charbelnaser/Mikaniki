"""Original parts catalog (EPC) of the user's car, by VIN, from 17VIN: categories -> diagram + OE numbers."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User, Vehicle
from ..schemas import PartCategoryOut, PartFindOut, PartListOut
from ..services import part_names, vin17
from .vehicles import get_owned_vehicle

router = APIRouter(prefix="/api/vehicles/{vehicle_id}/parts", tags=["parts"])
# No auth: <img> tags cannot send the token. Only 17VIN diagram names are accepted (vin17.SAFE_IMG).
image_router = APIRouter(prefix="/api/parts-img", tags=["parts"])


async def _epc(vehicle: Vehicle, db: Session) -> str:
    """The car's EPC brand code, decoded once from its VIN and kept in vin_data."""
    if not vin17.enabled():
        raise HTTPException(status_code=503, detail="The parts catalog is not configured")
    if not vehicle.vin:
        raise HTTPException(status_code=409, detail="Add the VIN of this car to open its parts catalog")
    epc = (vehicle.vin_data or {}).get("epc")
    if epc:
        return epc
    try:
        data = await vin17.decode_raw(vehicle.vin)
    except vin17.Vin17Error:
        raise HTTPException(status_code=503, detail="Parts catalog unavailable, please try again later")
    if not data or not data.get("epc"):
        raise HTTPException(status_code=404, detail="No parts catalog found for this VIN")
    # Reassign (not mutate) so SQLAlchemy saves the JSON column
    vehicle.vin_data = {**(vehicle.vin_data or {}), "epc": data["epc"], "epc_id": data.get("epc_id")}
    db.commit()
    return data["epc"]


@router.get("/categories", response_model=list[PartCategoryOut])
async def categories(
    vehicle_id: int,
    parent: str | None = Query(default=None, max_length=200),
    parent_level: int = Query(default=0, ge=0, le=2),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Top categories (no parent), or the sub-categories of `parent` (a category of level `parent_level`)."""
    if (parent is None) != (parent_level == 0):
        raise HTTPException(status_code=422, detail="parent and parent_level go together")
    vehicle = get_owned_vehicle(vehicle_id, user, db)
    epc = await _epc(vehicle, db)
    try:
        return await vin17.categories(epc, vehicle.vin, parent, parent_level)
    except vin17.Vin17Error:
        raise HTTPException(status_code=503, detail="Parts catalog unavailable, please try again later")


@router.get("/find", response_model=PartFindOut | None)
async def find_part(
    vehicle_id: int,
    q: str = Query(min_length=2, max_length=80),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Diagram + OE numbers for a generic part name ("ignition coil") on this car, or null.
    Never an error for a missing VIN / catalog: the chat then falls back to a generic photo."""
    vehicle = get_owned_vehicle(vehicle_id, user, db)
    try:
        epc = await _epc(vehicle, db)
        # Section names first (no LLM call); else the Chinese part-name list, which finds parts
        # filed under unrelated sections (e.g. the crank position sensor under "Cylinder Block")
        found = await vin17.find_part(epc, vehicle.vin, q)
        if found is None and (terms := await part_names.chinese_terms(q)):
            found = await vin17.find_part_by_name(epc, vehicle.vin, q, terms)
        return found
    except HTTPException as e:
        if e.status_code == 404 and e.detail == "Vehicle not found":
            raise
        return None
    except vin17.Vin17Error:
        return None


@router.get("", response_model=PartListOut)
async def part_list(
    vehicle_id: int,
    code: str = Query(min_length=1, max_length=200),
    level: int = Query(ge=1, le=3),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Parts of a last-level category: exploded diagram + OE numbers that fit this VIN."""
    vehicle = get_owned_vehicle(vehicle_id, user, db)
    epc = await _epc(vehicle, db)
    try:
        return await vin17.parts(epc, vehicle.vin, code, level)
    except vin17.Vin17Error:
        raise HTTPException(status_code=503, detail="Parts catalog unavailable, please try again later")


@image_router.get("/{epc}/{name}")
async def diagram(epc: str, name: str):
    """17VIN diagram served over our own HTTPS (their image host is HTTP only)."""
    image = await vin17.fetch_image(epc, name)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    content, media_type = image
    return Response(content, media_type=media_type, headers={"Cache-Control": "public, max-age=604800"})
