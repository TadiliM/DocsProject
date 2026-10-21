from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
