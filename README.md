# Mikaniki: AI mechanic for Lebanon

Mikaniki is a web app that diagnoses car problems for drivers in Lebanon. The user first identifies
their car (VIN, photo of the registration card, catalog or manual entry), then chats with an AI
mechanic. Every answer is specific to that exact car and gives:

- **likely causes**, ranked
- **severity**, and whether it is **safe to drive**
- **DIY difficulty**
- **estimated cost in Lebanon** in USD: parts (new or used) and labor

The UI is in **Arabic (RTL), English and French**, and the AI answers in Lebanese Arabic,
Arabizi, French or English, matching the user.

## Features

| Feature | How it works |
|---|---|
| Identify the car | VIN decoding (NHTSA vPIC, with 17VIN as a fallback for European, Korean and Chinese cars), VIN read from a photo of the registration card, catalog (makes popular in Lebanon first) or manual entry |
| Exact version | Engine, gearbox and fuel use from FuelEconomy.gov (US EPA) |
| Car-specific diagnosis chat | Photos, history and OBD-II codes. Safety rules make the AI tell the user to stop driving for brakes, steering, fuel leaks, overheating and similar problems |
| OBD-II codes | Code lookup from the OBDex database (CC0) |
| Safety reports | Recalls (US, Canada, UK), owner complaints and crash-test ratings for the car |
| Media under answers | Part photos (Wikimedia Commons), a "where is it on my car" image search, a PartSouq link by VIN and an embedded repair video (YouTube) |
| Parts catalog | The manufacturer's parts catalog by VIN, from 17VIN: sections, exploded diagrams and OE part numbers. Saying "show me the parts" in the chat opens it |

## Tech stack

```
mikaniki/
├── backend/    FastAPI, SQLAlchemy 2.0, pydantic-settings, provider-agnostic LLM layer (Claude / OpenAI / mock)
├── frontend/   Angular 20 (standalone components, signals, zoneless), Arabic (RTL) / English / French
└── docker-compose.yml
```

## Run locally

You need Python 3.12+ and Node.js 20+.

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env             # LLM_PROVIDER=mock works without any API key
uvicorn app.main:app --reload --port 8000
```

API docs are at http://localhost:8000/docs. Run the tests with `pytest -q`.

### 2. Frontend

```bash
cd frontend
npm install
npm start                        # http://localhost:4200, proxies /api and /uploads to :8000
```

The backend must be running, or the frontend shows `ECONNREFUSED` proxy errors.

### Docker

```bash
cp backend/.env.example backend/.env
docker compose up --build        # http://localhost:8080
```

## Configuration

All settings live in `backend/.env`. See [`backend/.env.example`](backend/.env.example) for the full list.

| Setting | Purpose |
|---|---|
| `LLM_PROVIDER` | `claude`, `openai` or `mock` (canned answers, no key needed) |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Claude |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | OpenAI |
| `DATABASE_URL` | SQLite by default. Postgres needs `psycopg[binary]` |
| `SECRET_KEY` | JWT signing key: set a long random string |
| `YOUTUBE_API_KEY` | Optional: embedded repair videos (otherwise a YouTube search link) |
| `WIKIMEDIA_CONTACT` | Optional: an email or URL, required by Wikimedia for part photos |
| `VIN17_USER`, `VIN17_PASSWORD` | Optional: a 17VIN **API** account (separate from a 17VIN website account) for the VIN fallback and the parts catalog |

Never commit `backend/.env`: it is gitignored.

## Data imports

```bash
cd backend
python scripts/import_obdex.py                              # OBD-II codes -> app/data/obdex_codes.json
python scripts/import_uk_recalls.py path/to/RecallsFile.csv # UK DVSA recalls -> app/data/uk_recalls.json
```

The DVSA site blocks automated downloads, so download `RecallsFile.csv` in a browser first.

## API overview

| Area | Endpoints |
|---|---|
| Auth | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `PATCH /api/auth/me/language` |
| Catalog | `GET /api/catalog/makes`, `/models`, `/versions`, `/vin/{vin}`, `POST /api/catalog/vin-photo` |
| Vehicles | `GET/POST /api/vehicles`, `GET/PATCH/DELETE /api/vehicles/{id}`, `GET /api/vehicles/{id}/reports` |
| Parts catalog | `GET /api/vehicles/{id}/parts/categories`, `GET /api/vehicles/{id}/parts` |
| Chat | `GET/POST /api/vehicles/{id}/conversations`, `GET/DELETE /api/conversations/{id}`, `POST /api/conversations/{id}/messages` |
| OBD-II | `GET /api/obd/{code}` |
| Media | `GET /api/media/part-photo`, `GET /api/media/video` |

## Architecture notes

- **The AI logic is channel-agnostic.** `app/services/diagnosis.py → reply_to_user()` is the single
  entry point. The web chat uses it today, and a WhatsApp channel or a mobile app can call it later
  (`Conversation.channel` and `User.phone` already exist).
- `app/services/prompts.py` builds the system prompt: a card describing the exact car, the Lebanese
  context, the safety rules and the answer format.
- The data model is `User → Vehicle → Conversation → Message`, with cascading deletes.

## Known limits and next steps

- NHTSA vPIC is a US database. The 17VIN fallback covers more brands, but needs a paid API account.
- Tables are created at startup with no migrations. Add Alembic before the schema changes.
- Uploaded photos are stored on local disk. Move them to S3/R2 with signed URLs for production.
- Next: voice notes, a WhatsApp channel, local parts prices, an installable PWA and rate limiting.

## Data sources

NHTSA vPIC, NHTSA recalls and complaints, Transport Canada recalls, UK DVSA recalls,
FuelEconomy.gov, OBDex (CC0), Wikimedia Commons, YouTube Data API and 17VIN. Each source keeps
its own terms of use.
