from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from ..schemas import ObdCauseOut, ObdCodeOut
from ..services import obd

router = APIRouter(prefix="/api/obd", tags=["obd"])


@router.get("/{code}", response_model=ObdCodeOut)
def lookup_code(code: str):
    codes = obd.extract_codes(code)
    if len(codes) != 1:
        raise HTTPException(status_code=422, detail="An OBD-II code looks like P0300: a letter (P, B, C or U) and 4 characters")
    result = obd.lookup(codes[0])
    data = asdict(result)
    data["causes"] = [ObdCauseOut(cause=c, likelihood=lk) for c, lk in result.causes]
    data["credit"] = obd.OBDEX_CREDIT if result.source == "obdex" else None
    return ObdCodeOut(**data)
