from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Mikaniki"
    secret_key: str = "dev-secret-change-me-use-at-least-32-characters"
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:4200"

    database_url: str = "sqlite:///./mikaniki.db"

    llm_provider: Literal["claude", "openai", "mock"] = "mock"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    llm_max_tokens: int = 4000

    youtube_api_key: str = ""  # optional: embedded repair videos in the chat (YouTube Data API v3)
    wikimedia_contact: str = ""
    # Optional: web photos under answers (services/images.py): "google" or "brave", or empty to disable
    image_search_provider: str = ""
    google_cse_key: str = ""
    google_cse_id: str = ""
    brave_api_key: str = ""  # email or URL sent to Wikimedia (required by their API policy) for part photos

    # Optional: 17VIN (paid, EPC data) decodes the VINs vPIC cannot (European, Chinese, Korean cars)
    vin17_user: str = ""
    vin17_password: str = ""

    upload_dir: str = "./uploads"
    max_upload_mb: int = 8

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
