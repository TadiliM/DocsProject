from io import BytesIO
from pathlib import Path
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

from app.config import Settings, get_settings
from app.database import get_connection
from app.main import app


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
def client():
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, max_upload_mb=1, max_pdf_pages=3
    )
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


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
