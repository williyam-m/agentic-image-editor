"""Runtime configuration.

Secrets are read from the project-level ``.env`` (git-ignored) or the process
environment. Nothing secret has a default value here.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLMs (DeepSeek via Azure, OpenAI-compatible) ---
    deepseek_pro_base_url: str
    deepseek_pro_model: str = "DeepSeek-V4-Pro"
    deepseek_pro_api_key: SecretStr
    deepseek_flash_base_url: str
    deepseek_flash_model: str = "DeepSeek-V4.1-Flash"
    deepseek_flash_api_key: SecretStr

    # --- Image generation (OpenAI) ---
    openai_api_key: SecretStr
    image_model: str = "gpt-image-2.5-flare"

    # --- Speech to text (ElevenLabs Scribe v2) — optional; voice editing is disabled without it ---
    elevenlabs_api_key: SecretStr | None = None
    stt_model: str = "scribe_v2"
    image_quality: str = "medium"

    # --- Infrastructure ---
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "crux-design"
    redis_url: str = "redis://localhost:6390/0"

    api_host: str = "127.0.0.1"
    api_port: int = 8787
    public_api_url: str = "http://localhost:8787"

    # --- Paths ---
    brand_kit_dir: Path = PROJECT_ROOT / "Candidate-resources" / "Brand-Kit"
    references_dir: Path = PROJECT_ROOT / "Candidate-resources" / "Image_Ad_References"
    data_dir: Path = PROJECT_ROOT / "data"
    fonts_dir: Path = BACKEND_ROOT / "assets" / "fonts"
    editor_dist_dir: Path = PROJECT_ROOT / "editor" / "dist"

    llm_timeout_s: float = Field(default=90.0)

    @field_validator("elevenlabs_api_key", mode="before")
    @classmethod
    def _empty_is_none(cls, v):  # "ELEVENLABS_API_KEY=" in .env means "not configured"
        return None if v is None or (isinstance(v, str) and not v.strip()) else v

    @property
    def brand_dir(self) -> Path:
        return self.data_dir / "brand"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def docs_dir(self) -> Path:
        return self.data_dir / "docs"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    s = Settings()  # type: ignore[call-arg]
    s.brand_dir.mkdir(parents=True, exist_ok=True)
    for d in (s.jobs_dir, s.docs_dir, s.uploads_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s
