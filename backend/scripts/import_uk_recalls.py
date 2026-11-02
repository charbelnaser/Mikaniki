"""
Import the UK DVSA vehicle recalls file into app/data/uk_recalls.json.

The DVSA site blocks automated downloads, so download the CSV once in your browser:
    https://www.check-vehicle-recalls.service.gov.uk/documents/RecallsFile.csv
(data: UK Crown Copyright, Open Government Licence v3.0), then run from backend/:
    python scripts/import_uk_recalls.py path/to/RecallsFile.csv

Column names have changed over the years, so they are matched by a few known spellings.
If a required column is not found, the script prints the headers it saw.
"""

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "uk_recalls.json"

COLUMNS = {
    "make": ["make", "manufacturer"],
    "models": ["recalls model information", "model information", "models", "model"],
    "model": ["model"],
    "ref": ["recalls number", "recall number", "recall ref", "recall reference", "reference", "dvsa reference"],
    "date": ["launch date", "recall date", "date"],
    "concern": ["concern"],
    "defect": ["defect", "description", "defect description"],
    "remedy": ["remedy", "remedy description"],
    "build_start": ["build start", "build start date", "build date from"],
    "build_end": ["build end", "build end date", "build date to"],
}
REQUIRED = ("make", "models", "ref", "defect")
DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%m/%d/%Y")

# The "Make" column often holds the UK company ("TOYOTA (GB) PLC", "MERCEDES BENZ UK LIMITED"):
# map it to car brands. Records are then matched on model name, so a group can safely span brands.
BRANDS = [
    "alfa romeo", "aston martin", "audi", "bentley", "bmw", "byd", "cadillac", "chery", "chevrolet",
    "chrysler", "citroen", "cupra", "dacia", "dodge", "ds", "ferrari", "fiat", "ford", "geely", "genesis",
    "honda", "hyundai", "infiniti", "isuzu", "jaguar", "jeep", "kia", "lamborghini", "land rover", "lexus",
    "maserati", "mazda", "mercedes-benz", "mg", "mini", "mitsubishi", "nissan", "opel", "peugeot",
    "porsche", "renault", "rolls royce", "seat", "skoda", "smart", "ssangyong", "subaru", "suzuki",
    "tesla", "toyota", "vauxhall", "volkswagen", "volvo",
]
BRAND_GROUPS = {
    "fiat chrysler": ["fiat", "jeep", "alfa romeo", "chrysler", "dodge", "abarth"],
    "stellantis": ["peugeot", "citroen", "ds", "opel", "fiat", "jeep", "alfa romeo"],
    "vauxhall": ["vauxhall", "opel"],      # Vauxhall models are sold as Opel elsewhere
    "vw": ["volkswagen"], "volkswagen": ["volkswagen"],
    "mercedes": ["mercedes-benz"], "daimler": ["mercedes-benz"],
    "landrover": ["land rover"], "range rover": ["land rover"],
    "rolls-royce": ["rolls royce"],
}


def brands_for(company: str) -> list[str]:
    """'TOYOTA (GB) PLC' -> ['toyota']; 'FIAT CHRYSLER AUTOMOBILES UK LTD' -> ['fiat', 'jeep', ...]."""
    name = re.sub(r"\s+", " ", company.lower().replace("-", " ")).strip()
    for prefix, brands in BRAND_GROUPS.items():
        if name.startswith(prefix.replace("-", " ")):
            return brands
    for brand in sorted(BRANDS, key=len, reverse=True):  # "land rover" before shorter names
        if re.match(rf"{re.escape(brand.replace('-', ' '))}\b", name):
            return [brand]
    return [name.split(" ")[0]] if name else []


def _parse_date(value: str | None) -> datetime | None:
    value = (value or "").strip().split(" ")[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _norm(header: str) -> str:
    return re.sub(r"\s+", " ", header.strip().lower().replace("_", " "))


def main(path: str) -> int:
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        headers = {_norm(h): h for h in reader.fieldnames or []}
        mapping = {key: next((headers[a] for a in aliases if a in headers), None) for key, aliases in COLUMNS.items()}
        missing = [k for k in REQUIRED if not mapping[k]]
        if missing:
            print(f"Missing columns {missing}. Headers found: {list(reader.fieldnames or [])}")
            return 1

        by_make: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)
        rows = 0
        for row in reader:
            rows += 1
            get = lambda k: (row.get(mapping[k]) or "").strip() if mapping[k] else ""  # noqa: E731
            ref = get("ref")
            # "Recalls Model Information" can list several models; "Model" is this row's model
            models = ", ".join(dict.fromkeys(m for m in (get("models"), get("model")) if m))
            brands = brands_for(get("make"))
            if not (brands and ref and models):
                continue
            start, end, date = _parse_date(get("build_start")), _parse_date(get("build_end")), _parse_date(get("date"))
            defect = " ".join(p for p in (get("concern"), get("defect")) if p)

            # The file has one row per model/VIN range: merge rows of the same recall and model text
            for brand in brands:
                record = by_make[brand].setdefault((ref, models), {
                    "ref": ref, "models": models, "date": date.strftime("%Y-%m-%d") if date else None,
                    "defect": defect, "remedy": get("remedy") or None,
                    "build_start_year": start.year if start else None, "build_end_year": end.year if end else None,
                })
                if start and (record["build_start_year"] is None or start.year < record["build_start_year"]):
                    record["build_start_year"] = start.year
                if end and (record["build_end_year"] is None or end.year > record["build_end_year"]):
                    record["build_end_year"] = end.year

    recalls = {make: list(items.values()) for make, items in sorted(by_make.items())}
    total = sum(len(v) for v in recalls.values())
    payload = {
        "_source": "UK DVSA vehicle recalls (Crown Copyright, Open Government Licence v3.0)",
        "_imported_at": datetime.now().strftime("%Y-%m-%d"),
        "recalls": recalls,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Read {rows} rows -> {total} recalls for {len(recalls)} makes in {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
