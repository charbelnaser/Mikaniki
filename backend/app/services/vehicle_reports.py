"""
Official safety data for a specific car: recalls, owner complaints and crash-test stars.

Sources (all free, no key):
- NHTSA (US) — https://api.nhtsa.gov : recalls, owner complaints, NCAP crash-test ratings.
- Transport Canada — https://data.tc.gc.ca : recalls for the Canadian market (many "US" imports
  in Lebanon are Canadian cars).
- UK DVSA — recalls for the UK/European market (Peugeot, Renault, EU-spec Kia/Hyundai...),
  imported offline into data/uk_recalls.json by scripts/import_uk_recalls.py.

Results are condensed into a short summary that is injected into the system prompt, so Claude
can cite real recalls and the most-reported problems for this exact make/model/year.
"""

import asyncio
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import httpx

NHTSA = "https://api.nhtsa.gov"
TC = "https://data.tc.gc.ca/v1.3/api/eng/vehicle-recall-database"
UK_FILE = Path(__file__).resolve().parent.parent / "data" / "uk_recalls.json"

TIMEOUT = 6                 # seconds per attempt (2 attempts, all calls in parallel: max ~12 s once a day per car)
TOP_COMPONENTS = 6          # most-reported components listed in the prompt
EXAMPLES_PER_COMPONENT = 2  # sample owner reports for the top 3 components
SNIPPET_CHARS = 220
MAX_CANADA_RECALLS = 8
MAX_UK_RECALLS = 8

_cache: dict[str, tuple[float, "VehicleReports"]] = {}
_TTL = 60 * 60 * 24


@dataclass
class Recall:
    campaign: str
    date: str | None
    component: str | None
    summary: str
    consequence: str | None
    remedy: str | None
    park_it: bool = False


@dataclass
class CanadaRecall:
    number: str
    date: str | None
    system: str | None
    kind: str | None          # e.g. "Safety TC", "Compliance Mfr"
    description: str | None


@dataclass
class UkRecall:
    ref: str
    date: str | None
    models: str | None
    defect: str | None
    remedy: str | None


@dataclass
class SafetyRating:
    description: str          # e.g. "2016 Toyota Corolla 4 DR FWD"
    overall: str | None
    frontal: str | None
    side: str | None
    rollover: str | None


@dataclass
class VehicleReports:
    recalls: list[Recall] = field(default_factory=list)
    recalls_canada: list[CanadaRecall] = field(default_factory=list)
    recalls_uk: list[UkRecall] = field(default_factory=list)
    safety: SafetyRating | None = None
    complaint_count: int = 0
    top_components: list[tuple[str, int]] = field(default_factory=list)
    examples: dict[str, list[str]] = field(default_factory=dict)
    crashes: int = 0
    fires: int = 0
    injuries: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.recalls or self.recalls_canada or self.recalls_uk or self.complaint_count or self.safety)


def _clean(text: str | None, limit: int | None = None) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split())
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


# --------------------------------------------------------------------------- NHTSA
def _nhtsa_date(value: str | None) -> str | None:
    """'17/01/2020' -> '2020-01-17' (same format as the Canada and UK dates)."""
    try:
        return datetime.strptime(value or "", "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return value


def parse_recalls(data: dict) -> list[Recall]:
    recalls = []
    for r in data.get("results") or []:
        summary = _clean(r.get("Summary"), 400)
        if not summary:
            continue
        recalls.append(Recall(
            campaign=r.get("NHTSACampaignNumber") or "?",
            date=_nhtsa_date(r.get("ReportReceivedDate")),
            component=_clean(r.get("Component")),
            summary=summary,
            consequence=_clean(r.get("Consequence"), 250),
            remedy=_clean(r.get("Remedy"), 200),
            park_it=bool(r.get("parkIt")),
        ))
    return recalls


def summarize_complaints(data: dict, reports: VehicleReports) -> None:
    results = data.get("results") or []
    reports.complaint_count = len(results)
    counts: Counter[str] = Counter()
    for c in results:
        for comp in (c.get("components") or "").split(","):
            if comp.strip():
                counts[comp.strip()] += 1
        reports.crashes += bool(c.get("crash"))
        reports.fires += bool(c.get("fire"))
        reports.injuries += c.get("numberOfInjuries") or 0
    reports.top_components = counts.most_common(TOP_COMPONENTS)

    # NHTSA returns the most recent complaints first
    for comp, _ in reports.top_components[:3]:
        snippets = [
            _clean(c.get("summary"), SNIPPET_CHARS)
            for c in results
            if comp in (c.get("components") or "") and c.get("summary")
        ]
        reports.examples[comp] = snippets[:EXAMPLES_PER_COMPONENT]


def parse_safety(data: dict) -> SafetyRating | None:
    rows = data.get("Results") or []
    if not rows:
        return None
    r = rows[0]
    return SafetyRating(
        description=r.get("VehicleDescription") or "",
        overall=r.get("OverallRating"),
        frontal=r.get("OverallFrontCrashRating"),
        side=r.get("OverallSideCrashRating"),
        rollover=r.get("RolloverRating"),
    )


# --------------------------------------------------------------------------- Transport Canada
def _tc_rows(data: dict) -> list[dict]:
    """TC returns [[{"Name": ..., "Value": {"Literal": ...}}, ...], ...] -> [{name: literal}]."""
    return [
        {cell.get("Name"): (cell.get("Value") or {}).get("Literal") for cell in row}
        for row in (data or {}).get("ResultSet") or []
    ]


def _tc_date(value: str | None) -> str | None:
    """'7/20/2017 12:00:00 AM' -> '2017-07-20'."""
    try:
        return datetime.strptime((value or "").split(" ")[0], "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return value


def parse_canada_recall(number: str, date: str | None, detail: dict | None) -> CanadaRecall:
    row = (_tc_rows(detail) or [{}])[0] if detail else {}
    return CanadaRecall(
        number=number,
        date=_tc_date(date),
        system=_clean(row.get("SYSTEM_TYPE_ETXT")),
        kind=_clean(row.get("NOTIFICATION_TYPE_ETXT")),
        description=_clean(row.get("COMMENT_ETXT"), 400),
    )


# --------------------------------------------------------------------------- UK DVSA (offline file)
def _norm(text: str) -> str:
    """Lowercase, hyphens as spaces: 'Mercedes-Benz' == 'MERCEDES BENZ', 'C-Class' == 'C CLASS'."""
    return re.sub(r"\s+", " ", text.lower().replace("-", " ")).strip()


MAKE_ALIASES = {"vw": "volkswagen", "mercedes": "mercedes benz", "chevy": "chevrolet"}


@lru_cache
def _uk_index() -> dict[str, list[dict]]:
    if not UK_FILE.is_file():
        return {}
    recalls = json.loads(UK_FILE.read_text(encoding="utf-8"))["recalls"]
    return {_norm(make): records for make, records in recalls.items()}


def uk_recalls_for(make: str, model: str, year: int) -> list[UkRecall]:
    """UK recalls whose model text mentions this model and whose build years include this year."""
    make_key = _norm(make)
    records = _uk_index().get(MAKE_ALIASES.get(make_key, make_key), [])
    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(_norm(model))}(?![a-z0-9])")
    found = []
    for r in records:
        if not pattern.search(_norm(r.get("models") or "")):
            continue
        start, end = r.get("build_start_year"), r.get("build_end_year")
        # Build year vs model year can differ by one
        if start and year < start - 1 or end and year > end + 1:
            continue
        found.append(UkRecall(ref=r["ref"], date=r.get("date"), models=_clean(r.get("models"), 120),
                              defect=_clean(r.get("defect"), 350), remedy=_clean(r.get("remedy"), 200)))
    found.sort(key=lambda r: r.date or "", reverse=True)
    return found[:MAX_UK_RECALLS]


# --------------------------------------------------------------------------- fetching
async def _fetch(client: httpx.AsyncClient, url: str, params: dict | None = None) -> dict | None:
    """One call with a single retry: these APIs are often slow or time out at random."""
    for _ in range(2):
        try:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError):
            continue
    return None


async def _canada(client: httpx.AsyncClient, make: str, model: str, year: int) -> list[CanadaRecall] | None:
    url = f"{TC}/recall/make-name/{quote(make.lower())}/model-name/{quote(model.lower())}/year-range/{year}-{year}"
    listing = await _fetch(client, url)
    if listing is None:
        return None
    rows = {r.get("Recall number"): r.get("Recall date") for r in _tc_rows(listing) if r.get("Recall number")}
    numbers = sorted(rows, key=lambda n: _tc_date(rows[n]) or "", reverse=True)[:MAX_CANADA_RECALLS]
    details = await asyncio.gather(
        *(_fetch(client, f"{TC}/recall-summary/recall-number/{quote(n)}") for n in numbers)
    )
    return [parse_canada_recall(n, rows[n], d) for n, d in zip(numbers, details)]


async def _safety(client: httpx.AsyncClient, make: str, model: str, year: int) -> SafetyRating | None | bool:
    """Crash-test stars. Returns False when NHTSA could not be reached (None = not rated)."""
    variants = await _fetch(client, f"{NHTSA}/SafetyRatings/modelyear/{year}/make/{quote(make)}/model/{quote(model)}")
    if variants is None:
        return False
    rows = variants.get("Results") or []
    if not rows or not rows[0].get("VehicleId"):
        return None
    detail = await _fetch(client, f"{NHTSA}/SafetyRatings/VehicleId/{rows[0]['VehicleId']}")
    return False if detail is None else parse_safety(detail)


async def get_vehicle_reports(make: str, model: str, year: int) -> VehicleReports | None:
    """All official safety data, or None if nothing could be reached (the chat works without it)."""
    key = f"{make.lower()}:{model.lower()}:{year}"
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]

    params = {"make": make, "model": model, "modelYear": year}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        recalls, complaints, canada, safety = await asyncio.gather(
            _fetch(client, f"{NHTSA}/recalls/recallsByVehicle", params),
            _fetch(client, f"{NHTSA}/complaints/complaintsByVehicle", params),
            _canada(client, make, model, year),
            _safety(client, make, model, year),
        )

    reports = VehicleReports(recalls_uk=uk_recalls_for(make, model, year))
    if recalls is not None:
        reports.recalls = parse_recalls(recalls)
    if complaints is not None:
        summarize_complaints(complaints, reports)
    if canada is not None:
        reports.recalls_canada = canada
    if safety is not False:
        reports.safety = safety

    online = [recalls, complaints, canada, None if safety is False else True]
    if all(x is None for x in online) and not reports.recalls_uk:
        return None
    # Only cache complete answers, so a partial one is retried on the next message
    if all(x is not None for x in online):
        _cache[key] = (time.time() + _TTL, reports)
    return reports


# --------------------------------------------------------------------------- prompt
def reports_section(reports: VehicleReports | None) -> str:
    """Prompt section with the official data. Empty string when there is nothing to add."""
    if reports is None or reports.is_empty:
        return ""

    lines = ["## Official safety data for this exact car (US NHTSA, Transport Canada, UK DVSA)"]
    if reports.recalls:
        lines.append(f"### US recalls (NHTSA): {len(reports.recalls)}")
        for r in reports.recalls:
            head = f"- **{r.campaign}** ({r.date or 'date unknown'}) — {r.component or 'component unknown'}"
            if r.park_it:
                head += " — ⚠ PARK IT: do not drive until fixed"
            lines.append(head)
            lines.append(f"  Problem: {r.summary}")
            if r.consequence:
                lines.append(f"  Risk: {r.consequence}")
            if r.remedy:
                lines.append(f"  Fix: {r.remedy}")
    else:
        lines.append("### US recalls (NHTSA): none on record.")

    if reports.recalls_canada:
        lines.append(f"### Canada recalls (Transport Canada): {len(reports.recalls_canada)}")
        for r in reports.recalls_canada:
            lines.append(f"- **TC {r.number}** ({r.date or 'date unknown'}) — {r.system or 'system unknown'}"
                         f"{f' [{r.kind}]' if r.kind else ''}")
            if r.description:
                lines.append(f"  {r.description}")

    if reports.recalls_uk:
        lines.append(f"### UK/European-market recalls (DVSA): {len(reports.recalls_uk)}")
        for r in reports.recalls_uk:
            lines.append(f"- **DVSA {r.ref}** ({r.date or 'date unknown'}) — models: {r.models or '?'}")
            if r.defect:
                lines.append(f"  Defect: {r.defect}")
            if r.remedy:
                lines.append(f"  Fix: {r.remedy}")

    if reports.safety:
        s = reports.safety
        lines.append(f"### US crash-test rating (NHTSA, {s.description}): overall {s.overall or '?'}/5 — "
                     f"frontal {s.frontal or '?'}, side {s.side or '?'}, rollover {s.rollover or '?'}")

    if reports.complaint_count:
        lines.append(f"### US owner complaints (NHTSA): {reports.complaint_count} filed")
        lines.append(f"Involving {reports.crashes} crashes, {reports.fires} fires, {reports.injuries} injuries.")
        lines.append("Most-reported components:")
        lines += [f"- {comp}: {n} complaints" for comp, n in reports.top_components]
        for comp, snippets in reports.examples.items():
            if snippets:
                lines.append(f"Example reports for {comp}:")
                lines += [f'  - "{s}"' for s in snippets]

    lines.append(
        "\nHow to use this data:\n"
        "- When a symptom matches a recall or a frequently reported component, say so explicitly and "
        "cite it (e.g. \"NHTSA recall 18V907000\", \"Transport Canada recall 2017363\" or \"one of the "
        "most reported problems on this car: 120 owner complaints about the engine\"). This is real data, "
        "use it to rank likely causes.\n"
        "- Each list is for one market (US, Canada, UK/Europe); the same problem often appears in several. "
        "Cars in Lebanon come from the US, Canada, Europe or the Gulf: tell the user to check with the "
        "brand's dealer in Lebanon (with the VIN) which recalls apply and whether they were done — the "
        "fix is usually free.\n"
        "- If a recall says PARK IT or involves fire, brakes, steering or airbags, warn the user clearly "
        "even if it is not related to their question.\n"
        "- Use the crash-test rating only when relevant (safety questions, buying a used car).\n"
        "- Complaints are unverified owner reports: treat them as signals, not proof. Do not invent "
        "numbers that are not listed here."
    )
    return "\n".join(lines)
