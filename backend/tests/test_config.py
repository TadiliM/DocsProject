import pytest
from pydantic import ValidationError

from app.config import Settings


def test_loads_dotenv_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MAX_UPLOAD_MB=2\nMAX_PDF_PAGES=20\nCHUNK_SIZE=500\nCHUNK_OVERLAP=100\n"
    )
    settings = Settings(_env_file=env_file)
    assert settings.max_upload_bytes == 2 * 1024 * 1024
    assert settings.max_pdf_pages == 20
    assert settings.chunk_size == 500
    assert settings.chunk_overlap == 100


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("MAX_UPLOAD_MB=2\n")
    monkeypatch.setenv("MAX_UPLOAD_MB", "3")
    assert Settings(_env_file=env_file).max_upload_mb == 3


@pytest.mark.parametrize(
    "values", [
        {"max_upload_mb": 0}, {"max_pdf_pages": 0}, {"max_upload_mb": "invalid"},
        {"chunk_size": 0}, {"chunk_overlap": -1},
        {"chunk_size": 100, "chunk_overlap": 100},
        {"chunk_size": 100, "chunk_overlap": 101},
        {"postgres_port": 0}, {"postgres_port": 65536},
        {"voyage_timeout_seconds": 0}, {"voyage_timeout_seconds": 121},
        {"voyage_batch_size": 0}, {"voyage_batch_size": 17},
        {"groq_timeout_seconds": 0}, {"groq_timeout_seconds": 121},
        {"llm_max_completion_tokens": 63}, {"llm_max_completion_tokens": 2049},
        {"llm_max_context_chars": 499}, {"llm_max_context_chars": 12001},
        {"rate_limit_requests": 0}, {"rate_limit_requests": 101},
        {"rate_limit_window_seconds": 0}, {"rate_limit_window_seconds": 3601},
    ]
)
def test_rejects_invalid_settings(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_voyage_key_is_masked():
    settings = Settings(_env_file=None, voyage_api_key="private-voyage-key")
    assert "private-voyage-key" not in repr(settings)
    assert settings.voyage_api_key.get_secret_value() == "private-voyage-key"


def test_groq_key_is_masked():
    settings = Settings(_env_file=None, groq_api_key="private-groq-key")
    assert "private-groq-key" not in repr(settings)
