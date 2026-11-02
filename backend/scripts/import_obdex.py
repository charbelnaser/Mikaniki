"""
Download the OBDex generic OBD-II code database and keep a trimmed English copy.

OBDex: https://github.com/foerbsnavi/OBDex — data under CC0-1.0 (public domain).
Run from backend/:  python scripts/import_obdex.py
Writes app/data/obdex_codes.json. Re-run whenever you want the latest data.

What we keep per code: title, a short explanation, top causes (with likelihood),
symptoms, repair difficulty / DIY, a few flags and related codes. We drop the German
text, the sources list and the EUR repair costs (European prices, not Lebanese).
"""

import json
import sys
from pathlib import Path

import httpx

URL = "https://foerbsnavi.github.io/OBDex/generic.min.json"
META_URL = "https://foerbsnavi.github.io/OBDex/meta.json"
OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "obdex_codes.json"

MAX_DESCRIPTION = 700
MAX_CAUSES = 6
MAX_SYMPTOMS = 5
MAX_RELATED = 6


def _en(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("en")
    return " ".join(value.split()) if isinstance(value, str) and value.strip() else None


def _shorten(text: str | None, limit: int) -> str | None:
    if not text or len(text) <= limit:
        return text
    cut = text[:limit]
    end = cut.rfind(". ")
    return cut[: end + 1] if end > limit // 2 else cut.rsplit(" ", 1)[0] + "…"


def trim(entry: dict) -> dict:
    repair = entry.get("repair") or {}
    flags = entry.get("flags") or {}
    out = {
        "title": _en(entry.get("title")),
        "description": _shorten(_en(entry.get("description")), MAX_DESCRIPTION),
        "causes": [
            [label, c.get("likelihood")]
            for c in (entry.get("common_causes") or [])[:MAX_CAUSES]
            if (label := _en(c.get("label")))
        ],
        "symptoms": [s for s in (_en(x) for x in (entry.get("symptoms") or [])[:MAX_SYMPTOMS]) if s],
        "difficulty": repair.get("difficulty"),
        "diy": repair.get("diy_possible"),
        "limp_mode": flags.get("limp_mode_possible"),
        "related": (entry.get("related_codes") or [])[:MAX_RELATED],
    }
    return {k: v for k, v in out.items() if v not in (None, [], "")}


def main() -> int:
    print(f"Downloading {URL} …")
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        r = client.get(URL)
        r.raise_for_status()
        entries = r.json()
        try:
            generated_at = client.get(META_URL).json().get("generated_at")
        except (httpx.HTTPError, ValueError):
            generated_at = None

    codes = {e["code"].upper(): trim(e) for e in entries if e.get("code")}
    payload = {
        "_source": "OBDex (https://github.com/foerbsnavi/obdex), CC0-1.0",
        "_generated_at": generated_at,
        "codes": dict(sorted(codes.items())),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(codes)} codes to {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
