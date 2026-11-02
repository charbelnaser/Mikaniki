"""
Exact engine / gearbox versions and official specs from FuelEconomy.gov (US EPA, free, no key).

https://www.fueleconomy.gov/feg/ws/ — covers cars sold in the US since 1984, which matches
the US imports common in Lebanon. The user picks their exact version when adding a car
("Auto (AV-S7), 4 cyl, 1.8 L"); we store the specs on the vehicle so every diagnosis knows
the exact gearbox (CVT vs 4-speed automatic matters a lot), drive and fuel consumption.
"""

import asyncio
import time

import httpx

EPA = "https://www.fueleconomy.gov/ws/rest/vehicle"
TIMEOUT = 10
MAX_MODEL_VARIANTS = 4   # e.g. "Camry" -> "Camry", "Camry Hybrid LE", ...
MPG_TO_L100 = 235.215

_cache: dict[str, tuple[float, object]] = {}
_TTL = 60 * 60 * 24 * 7


def _cached(key: str):
    hit = _cache.get(key)
    return hit[1] if hit and hit[0] > time.time() else None


def _store(key: str, value):
    _cache[key] = (time.time() + _TTL, value)
    return value


async def _get(client: httpx.AsyncClient, path: str, **params) -> dict:
    r = await client.get(f"{EPA}/{path}", params=params, headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json() if r.content else {}


def _menu_items(data: dict) -> list[dict]:
    items = (data or {}).get("menuItem") or []
    return items if isinstance(items, list) else [items]  # a single item comes back as an object


async def list_options(year: int, make: str, model: str) -> list[dict]:
    """Exact versions for a car: [{"id": 36800, "text": "...", "model": "Corolla"}]. Empty if unknown."""
    key = f"options:{year}:{make.lower()}:{model.lower()}"
    if (cached := _cached(key)) is not None:
        return cached

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # EPA model names are often more specific than ours ("Camry Hybrid LE", "4Runner 4WD")
        epa_models = [i["value"] for i in _menu_items(await _get(client, "menu/model", year=year, make=make))]
        wanted = model.strip().lower()
        matches = [m for m in epa_models if m.lower() == wanted]
        matches += [m for m in epa_models if m.lower().startswith(wanted) and m.lower() != wanted]
        matches = matches[:MAX_MODEL_VARIANTS]

        results = await asyncio.gather(
            *(_get(client, "menu/options", year=year, make=make, model=m) for m in matches)
        )

    options = []
    for epa_model, data in zip(matches, results):
        for item in _menu_items(data):
            text = item["text"] if epa_model.lower() == wanted else f"{epa_model} — {item['text']}"
            options.append({"id": int(item["value"]), "text": text, "model": epa_model})
    return _store(key, options)


def _l100(mpg: str | None) -> float | None:
    try:
        value = float(mpg or 0)
    except ValueError:
        return None
    return round(MPG_TO_L100 / value, 1) if value > 0 else None


def parse_specs(d: dict) -> dict:
    """Keep the fields that help a diagnosis, in metric units."""
    def val(k: str) -> str | None:
        v = str(d.get(k) or "").strip()
        return v or None

    displ = val("displ")
    specs = {
        "epa_id": int(d["id"]),
        "epa_model": val("model"),
        "transmission": val("trany"),               # "Automatic (AV-S7)" = CVT with 7 simulated steps
        "drive": val("drive"),
        "engine": f"{displ}L {val('cylinders')} cyl" if displ and val("cylinders") else (f"{displ}L" if displ else None),
        "engine_notes": val("eng_dscr"),
        "fuel": val("fuelType1") or val("fuelType"),
        "turbo": val("tCharger") == "T",
        "supercharger": val("sCharger") == "S",
        "start_stop": val("startStop") == "Y",
        "powertrain": val("atvType"),                # Hybrid, EV, Plug-in Hybrid, Diesel...
        "class": val("VClass"),
        "l_100km_combined": _l100(val("comb08")),
        "l_100km_city": _l100(val("city08")),
        "l_100km_highway": _l100(val("highway08")),
    }
    return {k: v for k, v in specs.items() if v not in (None, False, "")}


async def get_specs(epa_id: int) -> dict | None:
    """Official specs for one exact version, or None if EPA is unreachable."""
    key = f"specs:{epa_id}"
    if (cached := _cached(key)) is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            data = await _get(client, str(epa_id))
    except (httpx.HTTPError, ValueError):
        return None
    if not data.get("id"):
        return None
    return _store(key, parse_specs(data))
