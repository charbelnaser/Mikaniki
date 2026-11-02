"""
17VIN (https://en.17vin.com/doc.html): VIN decoding from the manufacturers' parts catalogs (EPC).

Paid and optional (VIN17_USER / VIN17_PASSWORD), used as a fallback for the VINs vPIC cannot decode:
European, Chinese and Korean cars, which are common in Lebanon. Only results that return data are
billed, and the same query repeated within 3 months is free.

Every request is signed: token = md5(md5(user) + md5(password) + "<path>?<query>"), where the
signed string is exactly the URL path and query that are sent, without user and token.
The decode also returns `epc` and `epc_id`, which the parts catalog by VIN (5101-5105) needs:
categories cata1 -> cata2 -> cata3 until `is_last`, then the part list with OE numbers and the
exploded diagram (http://resource.17vin.com/img/{epc}/{illustration_img_address}).
"""

import hashlib
import logging
import time
from urllib.parse import urlencode

import httpx

from ..config import get_settings
from ..schemas import VinDecodeOut

log = logging.getLogger(__name__)

API = "https://api.17vin.com:8443"
IMG_CAR = "http://resource.17vin.com/img/car/all/"
IMG_EPC = "http://resource.17vin.com/img/{epc}/{name}"

# Status codes (doc 2002) that mean our setup is wrong, as opposed to "no data for this VIN"
_SETUP_ERRORS = {1002: "missing user/token", 1004: "invalid token (check user and password)",
                 1005: "quota exhausted or account expired"}

_cache: dict[str, tuple[float, object]] = {}
_TTL = 60 * 60 * 24


class Vin17Error(Exception):
    pass


def enabled() -> bool:
    s = get_settings()
    return bool(s.vin17_user and s.vin17_password)


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def sign(path_and_query: str) -> str:
    s = get_settings()
    return _md5(_md5(s.vin17_user) + _md5(s.vin17_password) + path_and_query)


async def call(path: str, params: dict[str, str]) -> dict | None:
    """`data` of a successful call, None when 17VIN has no data. Raises Vin17Error on setup/network errors."""
    signed = f"{path}?{urlencode(params)}"
    url = f"{API}{signed}&{urlencode({'user': get_settings().vin17_user, 'token': sign(signed)})}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url)
            r.raise_for_status()
            body = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise Vin17Error(f"17VIN unreachable: {e}") from e
    code = body.get("code")
    if code == 1:
        return body.get("data") or None
    if code in _SETUP_ERRORS:
        raise Vin17Error(f"17VIN {code}: {_SETUP_ERRORS[code]} ({body.get('msg')})")
    return None  # 0 no data, 1003 brand not supported, 1006/1007 server side


async def balance() -> dict | None:
    """Account balance / remaining queries (doc 1002). Not billed."""
    return await call("/", {"action": "myapicount"})


def _get(row: dict, *keys: str) -> str | None:
    """First non-empty Latin-script value among keys (case-insensitive). Chinese-only values are skipped."""
    lower = {k.lower(): v for k, v in row.items()}
    for key in keys:
        v = lower.get(key.lower())
        if v is not None and str(v).strip() and str(v).isascii():
            return str(v).strip()
    return None


def _int(value) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def to_decode(vin: str, data: dict) -> VinDecodeOut:
    models = data.get("model_list") or data.get("model_import_list") or []
    m = models[0] if models else {}

    make = _get(m, "Brand") or _get(data, "brand") or (_get(data, "epc") or "").title() or None
    engine = " ".join(p for p in (
        f"{_get(m, 'Cc')}L" if _get(m, "Cc") else None,
        _get(m, "Air_intake"),
        f"({_get(m, 'Engine_no')})" if _get(m, "Engine_no") else None,
    ) if p) or None
    gearbox = " ".join(p for p in (_get(m, "Gear_num"), _get(m, "Transmission_detail")) if p) or None

    warnings = []
    if data.get("matching_mode") == "inexact_match" or len(models) > 1:
        warnings.append("Several versions match this VIN: check the engine and gearbox")

    images = [IMG_CAR + p.strip() for p in (_get(m, "Img_adress") or "").split(",") if p.strip()]
    raw = {k: v for k, v in data.items() if k not in ("model_list", "model_original_epc_list",
                                                      "model_gonggao_list", "model_import_list")}
    raw.update({"source": "17vin", "model_count": len(models), "model": m, "images": images[:3]})
    return VinDecodeOut(
        vin=vin,
        make=make,
        model=_get(m, "Model", "Series"),
        year=_int(_get(data, "model_year_from_vin") or _get(m, "Model_year")),
        trim=_get(m, "Sales_version", "Model_detial_en", "Model_detail_en"),
        engine=engine,
        fuel_type=_get(m, "Fuel_type"),
        transmission=gearbox,
        body_class=_get(m, "Body_type"),
        raw=raw,
        warnings=warnings,
    )


async def _cached_call(path: str, params: dict[str, str]) -> dict | None:
    """`call` with a 24 h memory cache: catalog pages are browsed back and forth."""
    key = f"{path}?{urlencode(params)}"
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    data = await call(path, params)
    _cache[key] = (time.time() + _TTL, data)
    return data


async def decode_raw(vin: str) -> dict | None:
    """Raw 3001 data (None if unknown VIN). Raises Vin17Error."""
    return await _cached_call("/", {"vin": vin})


async def decode_vin(vin: str) -> VinDecodeOut | None:
    """Decoded VIN, or None if 17VIN is disabled, unreachable or has no data for it (never raises)."""
    if not enabled():
        return None
    try:
        data = await decode_raw(vin)
    except Vin17Error as e:
        log.warning("%s", e)
        return None
    return to_decode(vin, data) if data else None


def _image(epc: str, name: str | None) -> str | None:
    return IMG_EPC.format(epc=epc, name=name.strip()) if name and name.strip() else None


def _fits(row: dict) -> bool:
    return str(row.get("is_fit_for_this_vin", row.get("Is_fit_for_this_vin", 1))) != "0"


def _name(row: dict) -> str:
    return (row.get("name_en") or row.get("name_zh") or "").strip()


async def categories(epc: str, vin: str, parent: str | None = None, parent_level: int = 0) -> list[dict]:
    """Catalog level parent_level + 1 (1-3). Raises Vin17Error."""
    level = parent_level + 1
    params = {"action": f"cata{level}", "vin": vin}
    if parent:
        params[f"cata{parent_level}_code"] = parent
    data = await _cached_call(f"/{epc}", params) or {}
    return [{
        "code": row.get("cata_code") or "",
        "name": _name(row),
        "name_zh": row.get("name_zh") or None,
        "remark": (row.get("remark_en") or row.get("remark_zh") or None),
        "level": int(row.get("cata_level") or level),
        "is_last": str(row.get("is_last")) == "1",
        "fits": _fits(row),
        "image": _image(epc, row.get("illustration_img_address")),
    } for row in data.get("catalist") or [] if row.get("cata_code")]


async def parts(epc: str, vin: str, cata_code: str, level: int) -> dict:
    """Part list of a last-level category: OE numbers + exploded diagram. Raises Vin17Error."""
    data = await _cached_call(f"/{epc}", {"action": "part", "vin": vin, "last_cata_code": cata_code,
                                          "last_cata_code_level": str(level)}) or {}
    rows = data.get("partlist") or []
    image = _image(epc, data.get("imgaddress") or next(
        (r.get("illustration_img_address") for r in rows if r.get("illustration_img_address")), None))
    return {
        "image": image,
        "parts": [{
            "callout": (row.get("callout") or "").strip() or None,
            "number": (row.get("partnumber_original") or row.get("partnumber") or "").strip(),
            "name": _name(row) or (row.get("std_name_en") or ""),
            "name_zh": row.get("name_zh") or None,
            "qty": (row.get("qty") or "").lstrip("0") or None,
            "remark": row.get("remark_en") or row.get("remark_zh") or None,
            "replacement": row.get("replacement") or None,
            "begin_date": row.get("begin_date") or None,
            "end_date": row.get("end_date") or None,
            "fits": _fits(row),
        } for row in rows if row.get("partnumber_original") or row.get("partnumber")],
    }
