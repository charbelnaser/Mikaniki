# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Mikaniki is an AI car mechanic web MVP for drivers in Lebanon. The user first identifies their car (catalog, VIN, or manual entry). Every chat answer is then specific to that car and covers likely causes, severity, whether it is safe to drive, DIY difficulty, and cost estimates in USD for Lebanon.

- `backend/`: FastAPI, SQLAlchemy 2.0 and pydantic-settings, with a provider-agnostic LLM layer.
- `frontend/`: Angular 20 using standalone components, signals and zoneless change detection. The UI is in Arabic (RTL), English and French.

## Commands

### Backend (run from `backend/`)

On this Windows machine `python` is not on PATH. Use the `py` launcher to create the venv; inside an activated venv, `python` and `pip` work.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                        # LLM_PROVIDER=mock needs no API key
uvicorn app.main:app --reload --port 8000   # API docs: http://localhost:8000/docs
```

Refresh the OBD-II code database (OBDex, CC0) into `app/data/obdex_codes.json`:

```powershell
python scripts/import_obdex.py
```

Import UK DVSA recalls into `app/data/uk_recalls.json`. The DVSA site blocks automated downloads, so download `RecallsFile.csv` in a browser first:

```powershell
python scripts/import_uk_recalls.py path\to\RecallsFile.csv
```

Tests use `pytest.ini`, which sets `testpaths=tests` and `pythonpath=.`:

```powershell
pytest -q                                          # all tests
pytest -q tests/test_api.py::test_vehicle_and_chat # a single test
```

`tests/test_api.py` sets its environment variables before importing `app`: a temporary SQLite DB, a temporary upload dir, `LLM_PROVIDER=mock` and a test `SECRET_KEY`. This order matters because `get_settings()` is `lru_cache`d and `db.py` creates the engine at import time. Network calls to NHTSA are avoided by monkeypatching `app.services.catalog` functions.

### Frontend (run from `frontend/`)

```powershell
npm install
npm start        # ng serve on http://localhost:4200, proxies /api and /uploads to :8000 (proxy.conf.json)
npm run build
```

The frontend has no test runner or linter configured.

### Docker

```powershell
docker compose up --build   # frontend (nginx) on :8080, backend on :8000, SQLite + uploads in a named volume
```

## Architecture

### Backend request flow

The app is created in `app/main.py`. It mounts four routers (`auth`, `catalog`, `vehicles`, `chat`), all under `/api`, and serves uploaded photos as static files from `/uploads`. Tables come from `Base.metadata.create_all` at startup; there is no Alembic yet, so schema changes to existing SQLite DBs are not migrated.

Authentication uses a JWT bearer token (`security.py`), and `deps.get_current_user` resolves the user. Ownership checks are done with helpers rather than query filters: `get_owned_vehicle` in `routers/vehicles.py` and `get_owned_conversation` in `routers/chat.py`. Both return 404 for another user's resource. New endpoints should reuse these helpers.

The data model is `User → Vehicle → Conversation → Message`, with cascading deletes. `Conversation.channel` (web, whatsapp or mobile) and `User.phone` already exist for future channels.

### The "brain" is channel-agnostic

- `services/diagnosis.py → reply_to_user()` is the single entry point. The web chat calls it today; WhatsApp and the mobile app are meant to call it later.
  - It saves the user message and any image, builds the system prompt, sends history to the LLM and stores the reply.
  - History is limited to the last 20 messages and the 2 most recent images.
  - On `LLMError` it **deletes the user message** so no dangling question is left; the router turns this into a 502 and the client restores the input for a retry.
- `services/prompts.py → build_system_prompt(vehicle, ui_language)` injects a "vehicle card" (make, model, year, engine, mileage, VIN data) plus Lebanese context and safety rules, and sets the answer language.
  - The mock provider parses the `- Model: ` line of this prompt, so keep that format if you edit the card.
- `services/llm.py` defines `LLMProvider.complete(system, turns)`, with `ClaudeProvider`, `OpenAIProvider` and `MockProvider` implementations.
  - `get_llm()` picks one from `LLM_PROVIDER` (claude, openai or mock).
  - Provider exceptions are wrapped in `LLMError`.
  - Images are sent as base64 in each provider's native format.

### Vehicle catalog

`services/catalog.py` merges the NHTSA vPIC API (free, US-market data) with the curated `app/data/lebanon_catalog.json`. The JSON file lists popular makes, shown first, and adds models that vPIC lacks, such as Peugeot, Renault and Chinese brands. Results are cached in memory for 24 hours, but only when vPIC responded, so outages are retried. VIN decoding goes through vPIC `DecodeVinValues`.

VINs that vPIC cannot decode (no model or year, or vPIC down) fall back to 17VIN (`services/vin17.py`), which is paid per successful result and enabled by `VIN17_USER`/`VIN17_PASSWORD`. Each request is signed with `md5(md5(user) + md5(password) + "<path>?<query>")`. 17VIN also powers the parts catalog by VIN (`routers/parts.py`, page `cars/:vehicleId/parts`): categories `cata1` → `cata2` → `cata3` until `is_last`, then the part list with OE numbers and the exploded diagram. The car's EPC code is decoded once and stored in `vin_data["epc"]`. In the chat, the LLM adds `"catalog": true` to the media tag when the user asks to see the parts, and `answer-media.ts` then shows a button to the catalog.

### Frontend

- `app.config.ts` sets up zoneless change detection, the `authInterceptor` (attaches the bearer token) and an app initializer that restores the logged-in user before the first render.
- Routes are lazy-loaded and protected by `authGuard` or `guestGuard`.
  - The chat uses a single route, `cars/:vehicleId/chat/:conversationId`, with `new` as the id for a new conversation. This lets the component be reused without a reload when a new conversation gets its id.
- `core/api.service.ts` wraps all backend calls, and `core/models.ts` mirrors the backend `schemas.py`. Keep the two in sync.
- i18n is a small runtime service, not Angular i18n.
  - `core/i18n.service.ts` holds a `lang` signal and sets `dir="rtl"` for Arabic.
  - Strings live in `core/translations.ts` as `en`, `fr` and `ar` dictionaries, with English as the fallback.
  - Components use `i18n.t(key, params)` or the `translate` pipe. Add every new UI string to all three dictionaries.

## Configuration

Settings come from `backend/.env`; see `.env.example`. The keys that matter most:
- `LLM_PROVIDER`, plus `ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL` or `OPENAI_API_KEY`/`OPENAI_MODEL`
- `DATABASE_URL`: SQLite by default; Postgres needs `psycopg[binary]`
- `SECRET_KEY`
- `CORS_ORIGINS`
- `UPLOAD_DIR` and `MAX_UPLOAD_MB`
- `VIN17_USER` and `VIN17_PASSWORD`: optional 17VIN API account (VIN fallback and parts catalog). API access must be enabled by 17VIN on the account.

## Known limits (from README)

- vPIC coverage is weak for European and Chinese models. Extend `lebanon_catalog.json` to fill the gaps.
- Uploads are stored on local disk. S3/R2 with signed URLs is planned for production.
- Planned next: Alembic, voice notes, a WhatsApp channel, RAG on OBD codes and local parts prices, a PWA, and rate limiting.
