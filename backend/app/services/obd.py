"""
OBD-II trouble codes: detection in user messages, official definitions, causes, severity.

Claude knows most generic codes, but can confuse them or invent meanings for
manufacturer-specific ones. We give it the definition, ranked causes and symptoms from
OBDex (data/obdex_codes.json, 9,500+ generic codes, CC0 — refresh with
scripts/import_obdex.py), our own severity ratings (data/obd_codes.json), decode the
code's structure when it is in neither, and remember which codes each car has
reported over time (ObdReading).
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data"
OBDEX_CREDIT = "OBD-II code data: OBDex (https://github.com/foerbsnavi/obdex), CC0-1.0"

# "P0300", "p0300", "P 0300", "P-0300"; not part of a longer word or number
CODE_RE = re.compile(r"(?<![A-Za-z0-9])([PBCUpbcu])[\s-]?([0-3][0-9A-Fa-f]{3})(?![A-Za-z0-9])")

SYSTEMS = {"P": "Powertrain (engine/transmission)", "B": "Body", "C": "Chassis", "U": "Network/communication"}
P_SUBSYSTEMS = {
    "0": "Fuel and air metering, auxiliary emission controls",
    "1": "Fuel and air metering",
    "2": "Fuel and air metering (injector circuit)",
    "3": "Ignition system or misfire",
    "4": "Auxiliary emission controls",
    "5": "Vehicle speed, idle control and auxiliary inputs",
    "6": "Computer and output circuits",
    "7": "Transmission", "8": "Transmission", "9": "Transmission",
    "A": "Hybrid propulsion", "B": "Hybrid propulsion", "C": "Hybrid propulsion",
}
COIL_LETTERS = "ABCDEFGHIJKL"
MAX_DETAILED = 6  # codes per conversation that get causes/symptoms in the prompt (token control)


@lru_cache
def _severities() -> dict[str, list[str]]:
    """Our curated [definition, severity] for common codes."""
    return json.loads((_DATA / "obd_codes.json").read_text(encoding="utf-8"))["codes"]


@lru_cache
def _obdex() -> dict[str, dict]:
    """OBDex data, loaded on first use. Empty if the import script was never run."""
    path = _DATA / "obdex_codes.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["codes"]


@dataclass
class ObdCode:
    code: str
    system: str
    generic: bool              # False = manufacturer-specific, meaning depends on the make
    definition: str | None     # None when we don't know the exact meaning
    severity: str | None       # low | medium | high (our rating; None = not rated)
    subsystem: str | None = None
    description: str | None = None
    causes: list[tuple[str, str]] = field(default_factory=list)  # (cause, likelihood high|medium|low)
    symptoms: list[str] = field(default_factory=list)
    difficulty: str | None = None
    diy_possible: bool | None = None
    limp_mode_possible: bool | None = None
    related: list[str] = field(default_factory=list)
    source: str | None = None  # "obdex" | "mikaniki" | None (structure only)


def extract_codes(text: str) -> list[str]:
    """Codes in a message, normalised and de-duplicated in order of appearance."""
    seen: dict[str, None] = {}
    for letter, digits in CODE_RE.findall(text or ""):
        seen[f"{letter}{digits}".upper()] = None
    return list(seen)


def _is_generic(code: str) -> bool:
    second = code[1]
    if code[0] == "P":
        return second in "02" or (second == "3" and code[2] in "456789ABCDEF")
    return second in "03"


def _family(code: str) -> tuple[str, str] | None:
    """Numbered code families: misfire / injector / ignition coil per cylinder."""
    if code[0] != "P" or not code[1:].isdigit():
        return None
    num = int(code[1:])  # "P0301" -> 301
    if 301 <= num <= 312:
        return f"Cylinder {num - 300} Misfire Detected", "high"
    if 201 <= num <= 212:
        return f"Injector Circuit/Open - Cylinder {num - 200}", "high"
    if 351 <= num <= 358:
        n = num - 350
        return f"Ignition Coil \"{COIL_LETTERS[n - 1]}\" Primary/Secondary Circuit (usually cylinder {n})", "high"
    return None


def lookup(code: str) -> ObdCode:
    code = code.strip().upper().replace(" ", "").replace("-", "")
    definition, severity = (_severities().get(code) or [None, None])
    source = "mikaniki" if definition else None
    if definition is None and (fam := _family(code)):
        definition, severity = fam
        source = "mikaniki"

    result = ObdCode(
        code=code, system=SYSTEMS[code[0]], generic=_is_generic(code),
        definition=definition, severity=severity, source=source,
        subsystem=P_SUBSYSTEMS.get(code[2]) if code[0] == "P" else None,
    )

    ox = _obdex().get(code)
    if ox:
        result.definition = ox.get("title") or result.definition
        result.description = ox.get("description")
        result.causes = [(c, likelihood or "unknown") for c, likelihood in ox.get("causes", [])]
        result.symptoms = ox.get("symptoms", [])
        result.difficulty = ox.get("difficulty")
        result.diy_possible = ox.get("diy")
        result.limp_mode_possible = ox.get("limp_mode")
        result.related = ox.get("related", [])
        result.source = "obdex"
    return result


def _describe(c: ObdCode, detailed: bool) -> str:
    severity = f"severity: {c.severity}" if c.severity else "severity: not rated, judge it yourself"
    if c.definition:
        head = f"- **{c.code}** — {c.definition} ({severity})"
    else:
        head = f"- **{c.code}** — exact definition not in our database"
    details = [c.system]
    if c.subsystem:
        details.append(c.subsystem)
    details.append("generic code" if c.generic else "MANUFACTURER-SPECIFIC code: meaning depends on the make")
    lines = [f"{head}. {'; '.join(details)}."]

    if detailed:
        if c.description:
            lines.append(f"  How it is detected: {c.description}")
        if c.causes:
            lines.append("  Common causes (generic, all makes): " + "; ".join(f"{t} [{lk}]" for t, lk in c.causes))
        if c.symptoms:
            lines.append("  Typical symptoms: " + "; ".join(c.symptoms))
        repair = []
        if c.difficulty:
            repair.append(f"difficulty {c.difficulty}")
        if c.diy_possible is not None:
            repair.append("DIY possible" if c.diy_possible else "not a DIY job")
        if c.limp_mode_possible:
            repair.append("car may go into limp mode")
        if repair:
            lines.append("  Repair: " + ", ".join(repair))
        if c.related:
            lines.append("  Related codes: " + ", ".join(c.related))
    return "\n".join(lines)


def codes_section(current: list[str], history: list[tuple[str, datetime]]) -> str:
    """Prompt section with the codes from this conversation and earlier ones on the same car."""
    if not current and not history:
        return ""
    lines = ["## OBD-II trouble codes (reference data — trust these definitions over memory)"]
    if current:
        lines.append("Reported in this conversation:")
        lines += [_describe(lookup(c), detailed=i < MAX_DETAILED) for i, c in enumerate(current)]
    if history:
        lines.append("Reported earlier on this same car (other conversations):")
        lines += [f"{_describe(lookup(c), detailed=False)} First reported {d:%Y-%m-%d}." for c, d in history]
    lines.append(
        "\nHow to use the codes:\n"
        "- Start from the definition above; never contradict it. A code says which circuit or system "
        "failed a test, not which part is broken.\n"
        "- The common causes listed are generic for all makes. Re-rank them for THIS car (its engine, "
        "mileage, known weak points, recalls and complaints above) and say why.\n"
        "- For a manufacturer-specific code or one without a definition here, say you are not certain of "
        "its exact meaning on this make; give your best interpretation and suggest confirming with a "
        "brand-specific scanner or the dealer. Never invent a definition.\n"
        "- Look for links between several codes (e.g. P0171 + P0174 = both banks lean, likely a vacuum "
        "leak or MAF; misfire + coil code on the same cylinder) and with codes reported earlier on this car.\n"
        "- If a misfire code comes with a FLASHING check-engine light, tell them to stop driving "
        "(catalytic converter damage).\n"
        "- Recommend clearing the code only after the repair, then re-checking it after a few drives.\n"
        "- Costs must still be Lebanese estimates in USD, as instructed above."
    )
    return "\n".join(lines)
