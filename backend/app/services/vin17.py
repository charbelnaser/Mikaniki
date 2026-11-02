"""
17VIN (https://en.17vin.com/doc.html): VIN decoding from the manufacturers' parts catalogs (EPC).

Paid and optional (VIN17_USER / VIN17_PASSWORD), used as a fallback for the VINs vPIC cannot decode:
European, Chinese and Korean cars, which are common in Lebanon. Only results that return data are
billed, and the same query repeated within 3 months is free.

Every request is signed: token = md5(md5(user) + md5(password) + "<path>?<query>"), where the
signed string is exactly the URL path and query that are sent, without user and token.
The decode also returns `epc` and `epc_id`, which the parts catalog by VIN (5101-5105) needs:
categories cata1 -> cata2 -> cata3 until `is_last`, then the part list with OE numbers and the
exploded diagram (http://resource.17vin.com/img/{epc}/{illustration_img_address}). That host has no
HTTPS, so diagrams are served to the browser through our own /api/parts-img (routers/parts.py).
Catalog browsing is not billed; only the VIN decode is (about 0.15 CNY).
"""

import asyncio
import hashlib
import logging
import re
import time
from urllib.parse import urlencode

import httpx

from ..config import get_settings
from ..schemas import VinDecodeOut

log = logging.getLogger(__name__)

API = "https://api.17vin.com:8443"
IMG_CAR = "http://resource.17vin.com/img/car/all/"
IMG_EPC = "http://resource.17vin.com/img/{epc}/{name}"
IMG_PROXY = "/api/parts-img/{epc}/{name}"
SAFE_EPC = re.compile(r"^[a-z0-9_-]{1,40}$")
SAFE_IMG = re.compile(r"^[A-Za-z0-9_.-]{1,80}\.(png|jpe?g|gif)$")

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


def epc_attributes(data: dict) -> dict[str, str]:
    """English attributes of the factory catalog entry (exact for this VIN), e.g.
    {"Model Code": "ZRE172L-DEXNKA", "Engine Code": "2ZRFE", "Grade": "LE", "ATM/MTM": "CVT"}."""
    rows = data.get("model_original_epc_list") or []
    if len(rows) != 1:
        return {}
    return {a["Col_name"]: str(a["Col_value"]).strip() for a in rows[0].get("CarAttributes") or []
            if a.get("Language") == "en" and a.get("Col_name") and str(a.get("Col_value") or "").strip()}


_FUELS = {"gas": "gasoline", "petrol": "gasoline"}
_GEARBOXES = {"ATM": "automatic", "AT": "automatic", "MTM": "manual", "MT": "manual"}


def to_decode(vin: str, data: dict) -> VinDecodeOut:
    """3001 response -> VinDecodeOut. `model_list` holds the standardised versions (several when the VIN
    does not pin one down); `model_original_epc_list` is the factory entry and wins when present."""
    models = data.get("model_list") or data.get("model_import_list") or []
    m = models[0] if models else {}
    epc = epc_attributes(data)

    cc = _get(m, "Cc_en", "Cc")
    if cc and not cc.upper().endswith("L"):
        cc += "L"
    aspiration = _get(m, "Air_intake_en")
    engine_code = _get(m, "Engine_no_en", "Engine_no") or epc.get("Engine Code")
    engine = " ".join(p for p in (
        cc,
        aspiration if aspiration and aspiration.lower() != "naturally aspirated" else None,
        f"({engine_code})" if engine_code else None,
    ) if p) or None

    gearbox = epc.get("ATM/MTM")
    if gearbox:
        gearbox = _GEARBOXES.get(gearbox.upper(), gearbox)
    elif len(models) == 1:  # with several versions, model_list's first gearbox is a guess
        gearbox = " ".join(p for p in (
            f"{_get(m, 'Gear_num_en')}-speed" if _get(m, "Gear_num_en") else None,
            _get(m, "Transmission_detail_en"),
        ) if p) or None
    fuel = _get(m, "Fuel_type_en")

    warnings = []
    if data.get("matching_mode") == "inexact_match" or (len(models) > 1 and not epc):
        warnings.append("Several versions match this VIN: check the engine and gearbox")

    images = [IMG_CAR + p.strip() for p in (_get(m, "Img_adress") or "").split(",") if p.strip()]
    raw = {k: v for k, v in data.items() if k not in ("model_list", "model_original_epc_list",
                                                      "model_gonggao_list", "model_import_list")}
    raw.update({"source": "17vin", "model_count": len(models), "model": m, "epc_attributes": epc,
                "images": images[:3]})
    return VinDecodeOut(
        vin=vin,
        make=_get(m, "Brand_en", "Brand") or _get(data, "brand") or (_get(data, "epc") or "").title() or None,
        model=_get(m, "Model_en", "Series_en", "Model", "Series") or (epc.get("Model Name") or "").title() or None,
        year=_int(_get(data, "model_year_from_vin") or _get(m, "Model_year")),
        trim=epc.get("Grade") or _get(m, "Sales_version_en", "Sales_version"),
        engine=engine,
        fuel_type=_FUELS.get((fuel or "").lower(), fuel),
        transmission=gearbox,
        body_class=_get(m, "Body_type_en"),
        plant_country=_get(data, "made_in_en"),
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
    """Diagram URL through our image proxy (17VIN images are HTTP only)."""
    name = (name or "").strip()
    return IMG_PROXY.format(epc=epc, name=name) if SAFE_EPC.match(epc) and SAFE_IMG.match(name) else None


async def fetch_image(epc: str, name: str) -> tuple[bytes, str] | None:
    """Diagram bytes + media type, cached 24 h. None if invalid name or not found."""
    if not (SAFE_EPC.match(epc) and SAFE_IMG.match(name)):
        return None
    key = f"img:{epc}/{name}"
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(IMG_EPC.format(epc=epc, name=name))
    except httpx.HTTPError:
        return None
    if r.status_code != 200 or not r.content:
        return None
    ext = name.rsplit(".", 1)[1].lower()
    result = (r.content, "image/png" if ext == "png" else "image/gif" if ext == "gif" else "image/jpeg")
    _cache[key] = (time.time() + _TTL, result)
    return result


def _fits(row: dict) -> bool:
    return str(row.get("is_fit_for_this_vin", row.get("Is_fit_for_this_vin", 1))) != "0"


_CODE_PREFIX = re.compile(r"^\d+(_\d+)?\s+")  # "1901_0001 Ignition coil" / "1 Engine"
_ZH_NAMES = {"标准件": "Standard hardware (bolt, nut, clip)"}


def _name(row: dict) -> str:
    """English name without the catalog code prefix; Toyota-style CAPS -> Title case."""
    name = (row.get("name_en") or "").strip() or _ZH_NAMES.get((row.get("name_zh") or "").strip())         or (row.get("name_zh") or "").strip()
    name = _CODE_PREFIX.sub("", name).replace(",", ", ").replace("  ", " ")
    return name.title() if name.isupper() else name


def _hotspots(data: dict, image_name: str | None) -> list[dict]:
    """Callout positions on the diagram, in % of its size (deduplicated)."""
    seen, out = set(), []
    for img in data.get("all_img_hotspots") or []:
        info = img.get("img_hotspots") or {}
        w, h = info.get("img_width") or 0, info.get("img_height") or 0
        if not (w and h) or (image_name and info.get("img_name") != image_name):
            continue
        for spot in info.get("hotspots") or []:
            callout = (spot.get("callout") or "").strip()
            x, y = spot.get("topleft_x"), spot.get("topleft_y")
            if callout and x is not None and y is not None and (callout, x, y) not in seen:
                seen.add((callout, x, y))
                out.append({"callout": callout, "x": round(100 * x / w, 2), "y": round(100 * y / h, 2)})
    return out


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
    image_name = data.get("imgaddress") or next(
        (r.get("illustration_img_address") for r in rows if r.get("illustration_img_address")), None)
    return {
        "image": _image(epc, image_name),
        "hotspots": _hotspots(data, image_name),
        "parts": [{
            "callout": (row.get("callout") or "").strip() or None,
            "number": (row.get("partnumber") or row.get("partnumber_original") or "").strip(),
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


# ---------------------------------------------------------------- part name -> catalog section
_WORD = re.compile(r"[a-z]+")


def _words(text: str) -> set[str]:
    """Lower-case words, plural 's' dropped: 'Ignition coils' -> {'ignition', 'coil'}."""
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in _WORD.findall(text.lower()) if len(w) > 2}


def _score(name: str, words: set[str]) -> int:
    return len(words & _words(name))


# Words that turn a part into something else: "Pad, Brake Pedal" is not a brake pad, "Bolt(For Alternator)"
# is not the alternator. A part name with one of these (absent from the query) ranks below exact parts.
_CONTEXT = {"pedal", "bracket", "bolt", "nut", "clip", "gasket", "cover", "union", "washer", "seal", "hose",
            "clamp", "carrier", "label", "plate", "pin", "screw", "stud", "grommet", "cushion", "insulator"}


def _part_score(name: str, words: set[str]) -> tuple[int, int]:
    """(query words matched, 1 if the name is the thing itself rather than an accessory of it)."""
    own = _words(name)
    accessory = "(for" in name.lower() or bool((own & _CONTEXT) - words)
    return len(words & own), 0 if accessory else 1


async def find_part(epc: str, vin: str, query: str) -> dict | None:
    """Catalog section + diagram that best match a generic English part name ("ignition coil").

    Walks the category tree (free calls, cached): every top category, then only the sub-categories whose
    name shares a word with the query; scores the last-level sections by name, then confirms the best
    few with their part lists. Returns None when nothing matches. Raises Vin17Error.
    """
    words = _words(query)
    if not words:
        return None
    sections: list[dict] = []
    frontier = await categories(epc, vin)
    while frontier:
        sections += [c for c in frontier if c["is_last"] and c["fits"]]
        deeper = [c for c in frontier if not c["is_last"] and c["level"] < 3 and (c["level"] == 1 or _score(c["name"], words))]
        lists = await asyncio.gather(*(categories(epc, vin, c["code"], c["level"]) for c in deeper))
        frontier = [c for sub in lists for c in sub]
    candidates = sorted((c for c in sections if _score(c["name"], words)), key=lambda c: -_score(c["name"], words))[:10]
    if not candidates:
        return None

    best = None
    for section, plist in zip(candidates, await asyncio.gather(*(parts(epc, vin, c["code"], c["level"]) for c in candidates))):
        matched = [p for p in plist["parts"] if p["fits"] and _score(p["name"], words)]
        top = max((_part_score(p["name"], words) for p in matched), default=(0, 0))
        score = (*top, _score(section["name"], words))
        if best is None or score > best[0]:
            best = (score, section, plist, [p for p in matched if _part_score(p["name"], words) == top])
    (part_words, itself, section_words), section, plist, matched = best
    if part_words < len(words) and section_words < len(words):
        return None  # e.g. "wheel bearing" only matching "Wheel, Disc": better no diagram than a wrong one
    if part_words and not itself:
        return None  # only accessories of it ("Cover, Timing Chain" for "timing chain")
    callouts = {p["callout"] for p in matched if p["callout"]}
    return {
        "section": {"code": section["code"], "name": section["name"], "level": section["level"]},
        "image": plist["image"],
        "hotspots": [h for h in plist["hotspots"] if h["callout"] in callouts],
        "parts": matched[:3],
    }
