"""
Vehicle catalog: makes, models and VIN decoding.

Primary source: NHTSA vPIC (free, no key) — https://vpic.nhtsa.dot.gov/api/
Its coverage is the US market, which fits the many US imports in Lebanon, but it
misses most European/Chinese models sold locally (Peugeot, Renault, Chery, BYD...).
So we merge it with a small curated list of models common in Lebanon
(data/lebanon_catalog.json). The UI always allows typing a model by hand as well.
VINs that vPIC cannot decode go to 17VIN when it is configured (services/vin17.py).
"""

import json
import time
from pathlib import Path

import httpx

from ..schemas import MakeOut, ModelOut, VinDecodeOut
from . import vin17

VPIC = "https://vpic.nhtsa.dot.gov/api/vehicles"
_CATALOG_FILE = Path(__file__).resolve().parent.parent / "data" / "lebanon_catalog.json"
_LOCAL = json.loads(_CATALOG_FILE.read_text(encoding="utf-8"))

POPULAR_MAKES: list[str] = _LOCAL["popular_makes"]
LOCAL_MODELS: dict[str, list[str]] = {k.lower(): v for k, v in _LOCAL["models"].items()}

# Very small in-memory cache: key -> (expires_at, value)
_cache: dict[str, tuple[float, object]] = {}
_TTL = 60 * 60 * 24


def _cached(key: str):
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def _store(key: str, value):
    _cache[key] = (time.time() + _TTL, value)
    return value


def _nice(name: str | None) -> str | None:
    """vPIC returns 'TOYOTA' / 'MERCEDES-BENZ' -> 'Toyota' / 'Mercedes-Benz'. Keep short acronyms (BMW, GMC)."""
    if not name:
        return None
    name = name.strip()
    if len(name) <= 3:
        return name.upper()
    return "-".join(part.capitalize() for part in name.title().split("-"))


async def _get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{VPIC}/{path}", params={"format": "json"})
        r.raise_for_status()
        return r.json()


async def list_makes() -> list[MakeOut]:
    cached = _cached("makes")
    if cached is not None:
        return cached

    names: dict[str, MakeOut] = {}
    vpic_ok = False
    for vehicle_type in ("car", "multipurpose passenger vehicle (mpv)"):
        try:
            data = await _get(f"GetMakesForVehicleType/{vehicle_type}")
            vpic_ok = True
        except httpx.HTTPError:
            continue
        for row in data.get("Results", []):
            nice = _nice(row.get("MakeName"))
            if nice and nice.lower() not in names:
                names[nice.lower()] = MakeOut(id=row.get("MakeId"), name=nice)

    # Make sure locally popular brands exist even if vPIC is down or lacks them
    for make in POPULAR_MAKES + list(_LOCAL["models"].keys()):
        names.setdefault(make.lower(), MakeOut(name=make))

    popular = {m.lower() for m in POPULAR_MAKES}
    result = []
    for key, make in names.items():
        make.popular = key in popular
        if make.popular:
            make.name = next(p for p in POPULAR_MAKES if p.lower() == key)  # preferred spelling
        result.append(make)

    order = {m.lower(): i for i, m in enumerate(POPULAR_MAKES)}
    result.sort(key=lambda m: (not m.popular, order.get(m.name.lower(), 0), m.name))
    # Only cache when vPIC answered (otherwise retry next time)
    return _store("makes", result) if vpic_ok else result


async def list_models(make: str, year: int) -> list[ModelOut]:
    key = f"models:{make.lower()}:{year}"
    cached = _cached(key)
    if cached is not None:
        return cached

    models: dict[str, ModelOut] = {}
    try:
        data = await _get(f"GetModelsForMakeYear/make/{make}/modelyear/{year}")
        for row in data.get("Results", []):
            name = (row.get("Model_Name") or "").strip()
            if name:
                models.setdefault(name.lower(), ModelOut(id=row.get("Model_ID"), name=name))
        vpic_ok = True
    except httpx.HTTPError:
        vpic_ok = False

    for name in LOCAL_MODELS.get(make.lower(), []):
        models.setdefault(name.lower(), ModelOut(name=name))

    result = sorted(models.values(), key=lambda m: m.name)
    return _store(key, result) if vpic_ok else result


def _int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


async def decode_vin(vin: str) -> VinDecodeOut:
    """vPIC first (free); 17VIN (paid) only when vPIC is down or cannot name the model and year."""
    vin = vin.strip().upper()
    try:
        result = await _decode_vpic(vin)
    except httpx.HTTPError:
        result = None
    if result and result.model and result.year:
        return result
    fallback = await vin17.decode_vin(vin)
    if fallback:
        return fallback
    if result is None:
        raise httpx.HTTPError("vPIC unreachable and no 17VIN result")
    return result


async def _decode_vpic(vin: str) -> VinDecodeOut:
    data = await _get(f"DecodeVinValues/{vin}")
    row = (data.get("Results") or [{}])[0]

    def val(k: str) -> str | None:
        v = (row.get(k) or "").strip()
        return v or None

    engine_parts = []
    if val("DisplacementL"):
        try:
            engine_parts.append(f"{float(val('DisplacementL')):.1f}L")
        except ValueError:
            engine_parts.append(f"{val('DisplacementL')}L")
    if val("EngineConfiguration") and val("EngineCylinders"):
        cfg = val("EngineConfiguration")
        prefix = "V" if "V" in cfg.upper() else ("I" if "IN-LINE" in cfg.upper() else "")
        engine_parts.append(f"{prefix}{val('EngineCylinders')}" if prefix else f"{val('EngineCylinders')} cyl")
    elif val("EngineCylinders"):
        engine_parts.append(f"{val('EngineCylinders')} cyl")
    if val("Turbo") and val("Turbo").lower() == "yes":
        engine_parts.append("turbo")
    if val("ElectrificationLevel"):
        engine_parts.append(val("ElectrificationLevel"))

    warnings = []
    error_code = val("ErrorCode") or "0"
    if not error_code.startswith("0"):
        warnings.append(val("ErrorText") or "VIN could not be fully decoded")

    return VinDecodeOut(
        vin=vin,
        make=_nice(val("Make")),
        model=val("Model"),
        year=_int(val("ModelYear")),
        trim=val("Trim") or val("Series"),
        engine=" ".join(engine_parts) or None,
        fuel_type=val("FuelTypePrimary"),
        transmission=val("TransmissionStyle"),
        body_class=val("BodyClass"),
        plant_country=val("PlantCountry"),
        raw={k: v for k, v in row.items() if v not in (None, "", "Not Applicable")},
        warnings=warnings,
    )
