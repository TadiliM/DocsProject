from io import BytesIO
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)
from psycopg import sql

from app.auth import require_admin_key
from app.config import Settings, get_settings
from app.database import check_database, get_connection
from app.embeddings import EmbeddingResult
from app.main import app
from app.repository import create_document
from app.schemas import StoredDocument


def pytest_addoption(parser):
    parser.addoption(
        "--run-db-tests", action="store_true", default=False,
        help="Run integration tests against the configured local PostgreSQL database.",
    )


@pytest.fixture
def db_connection(request):
    if not request.config.getoption("--run-db-tests"):
        pytest.skip("Use --run-db-tests with PostgreSQL running.")

    # Each test gets separate tables; the public library is never modified.
    schema = "test_" + uuid4().hex
    settings = Settings()
    with get_connection(settings) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(
            sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
        )
        connection.commit()
        try:
            schema_file = Path(__file__).resolve().parents[1] / "sql" / "001_init.sql"
            connection.execute(schema_file.read_text())
            connection.commit()
            yield connection, schema
        finally:
            connection.rollback()
            connection.execute("SET search_path TO public")
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )
            connection.commit()


@pytest.fixture
def upload_mocks(monkeypatch):
    def embed(texts, settings):
        return EmbeddingResult(
            embeddings=[[(index + 1) / 10] * 1024 for index, _ in enumerate(texts)],
            total_tokens=len(texts) * 10,
        )

    def save(connection, filename, page_count, chunks, embeddings):
        return StoredDocument(
            id=123, filename=filename, page_count=page_count,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    mocks = {
        "check_database": Mock(return_value=True),
        "embed_documents": Mock(side_effect=embed),
        "create_document": Mock(side_effect=save),
        "get_connection": Mock(side_effect=lambda settings: nullcontext(object())),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(f"app.main.{name}", mock)
    return mocks


@pytest.fixture
def client(upload_mocks):
    # Business-logic tests bypass authentication. test_auth.py tests real auth.
    app.dependency_overrides[require_admin_key] = lambda: None
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, max_upload_mb=1, max_pdf_pages=3
    )
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def library_client(db_connection, client, monkeypatch):
    """Exercise real SQL through the API, isolating all writes in a test schema."""
    _, schema = db_connection
    settings = Settings()
    app.dependency_overrides[get_settings] = lambda: settings

    @contextmanager
    def isolated_connection(settings):
        with get_connection(settings) as connection:
            connection.execute(
                sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema))
            )
            connection.commit()
            yield connection

    monkeypatch.setattr("app.main.get_connection", isolated_connection)
    monkeypatch.setattr("app.retrieval.get_connection", isolated_connection)
    monkeypatch.setattr("app.main.create_document", create_document)
    monkeypatch.setattr("app.main.check_database", check_database)
    return client


@pytest.fixture
def make_pdf():
    """Build small real PDFs without another PDF generation dependency."""
    def build(texts, password=None):
        writer = PdfWriter()
        for text in texts:
            page = writer.add_blank_page(width=612, height=792)
            if text:
                font = DictionaryObject({
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                })
                page[NameObject("/Resources")] = DictionaryObject({
                    NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
                })
                escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                stream = DecodedStreamObject()
                stream.set_data(
                    f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
                )
                page[NameObject("/Contents")] = writer._add_object(stream)
        if password is not None:
            writer.encrypt(password)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    return build
