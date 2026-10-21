from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EMBEDDING_MODEL = "voyage-4-lite"
EMBEDDING_DIMENSIONS = 1024
LLM_MODEL = "qwen/qwen3.8-27b"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    max_upload_mb: int = Field(default=10, ge=1, le=50)
    max_pdf_pages: int = Field(default=100, ge=1, le=500)
    chunk_size: int = Field(default=1000, ge=1, le=10000)
    chunk_overlap: int = Field(default=200, ge=0, le=9999)
    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5433, ge=1, le=65535)
    postgres_db: str = "docsproject"
    postgres_user: str = "docsproject"
    postgres_password: SecretStr = SecretStr("docsproject_local_only")
    voyage_api_key: SecretStr = SecretStr("")
    voyage_timeout_seconds: float = Field(default=30, gt=0, le=120)
    voyage_batch_size: int = Field(default=16, ge=1, le=16)
    groq_api_key: SecretStr = SecretStr("")
    groq_timeout_seconds: float = Field(default=30, gt=0, le=120)
    llm_max_completion_tokens: int = Field(default=512, ge=64, le=2048)
    llm_max_context_chars: int = Field(default=6000, ge=500, le=12000)
    rate_limit_requests: int = Field(default=3, ge=1, le=100)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    admin_api_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE.")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
