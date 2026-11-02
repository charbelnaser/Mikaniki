from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import init_db
from .routers import auth, catalog, chat, media, obd, parts, vehicles

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # For production, switch to Alembic migrations
    yield


app = FastAPI(title=f"{settings.app_name} API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(vehicles.router)
app.include_router(chat.router)
app.include_router(obd.router)
app.include_router(media.router)
app.include_router(parts.router)

# Uploaded photos use random UUID names. For production, move them to S3/R2 with signed URLs.
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_provider": settings.llm_provider}
