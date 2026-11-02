from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User, Vehicle
from ..schemas import (
    ComplaintComponentOut, RecallOut, SafetyRatingOut, VehicleCreate, VehicleOut, VehicleReportsOut, VehicleUpdate,
)
from ..services import epa, vehicle_reports

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


def get_owned_vehicle(vehicle_id: int, user: User, db: Session) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.user_id != user.id:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


@router.get("", response_model=list[VehicleOut])
def list_vehicles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Vehicle).where(Vehicle.user_id == user.id).order_by(Vehicle.created_at.desc())).all()


@router.post("", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
async def create_vehicle(body: VehicleCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    vehicle = Vehicle(user_id=user.id, **body.model_dump(exclude={"epa_id"}))
    if body.epa_id:
        # Fetched server-side (never trust specs sent by the client: they end up in the AI prompt)
        vehicle.specs = await epa.get_specs(body.epa_id)
        if vehicle.specs and not vehicle.engine:
            vehicle.engine = vehicle.specs.get("engine")
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.get("/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(vehicle_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_owned_vehicle(vehicle_id, user, db)


@router.get("/{vehicle_id}/reports", response_model=VehicleReportsOut)
async def get_vehicle_reports(vehicle_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Recalls, owner complaints and crash-test stars for the car card. Also warms the cache for the chat."""
    v = get_owned_vehicle(vehicle_id, user, db)
    reports = await vehicle_reports.get_vehicle_reports(v.make, v.model, v.year)
    if reports is None:
        return VehicleReportsOut(available=False)
    s = reports.safety
    recalls = [
        *(RecallOut(market="US", ref=r.campaign, date=r.date, component=r.component, summary=r.summary,
                    consequence=r.consequence, remedy=r.remedy, park_it=r.park_it) for r in reports.recalls),
        *(RecallOut(market="CA", ref=r.number, date=r.date, component=r.system, summary=r.description)
          for r in reports.recalls_canada),
        *(RecallOut(market="UK", ref=r.ref, date=r.date, component=r.models, summary=r.defect, remedy=r.remedy)
          for r in reports.recalls_uk),
    ]
    recalls.sort(key=lambda r: r.date or "", reverse=True)
    return VehicleReportsOut(
        available=True,
        recalls_us=len(reports.recalls),
        recalls_canada=len(reports.recalls_canada),
        recalls_uk=len(reports.recalls_uk),
        complaints=reports.complaint_count,
        safety=SafetyRatingOut(
            description=s.description, overall=s.overall, frontal=s.frontal, side=s.side, rollover=s.rollover,
        ) if s else None,
        recalls=recalls,
        top_components=[
            ComplaintComponentOut(component=comp, count=n, examples=reports.examples.get(comp, []))
            for comp, n in reports.top_components
        ],
        crashes=reports.crashes,
        fires=reports.fires,
        injuries=reports.injuries,
    )


@router.patch("/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(
    vehicle_id: int, body: VehicleUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    vehicle = get_owned_vehicle(vehicle_id, user, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(vehicle, field, value)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle(vehicle_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(get_owned_vehicle(vehicle_id, user, db))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
