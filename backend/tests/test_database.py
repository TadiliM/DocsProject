import json
import traceback
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from app.config import Settings
from app.database import check_database, get_connection
from app.repository import create_document, get_document, get_document_chunks
from app.schemas import DocumentChunk


def sample_chunks():
    return [
        DocumentChunk(chunk_index=0, page_number=1, text="First passage."),
        DocumentChunk(chunk_index=1, page_number=2, text="Second passage."),
    ]


def sample_embeddings():
    return [[0.1] * 1024, [0.2] * 1024]


def test_saves_document_and_chunks_and_commits(db_connection):
    connection, schema = db_connection
    document = create_document(connection, "Intern's guide.pdf", 2, sample_chunks(), sample_embeddings())

    # A separate connection can see the committed document.
    with get_connection(Settings()) as other:
        row = other.execute(
            sql.SQL("SELECT filename FROM {}.documents WHERE id = %s").format(
                sql.Identifier(schema)
            ),
            (document.id,),
        ).fetchone()
        assert row["filename"] == "Intern's guide.pdf"

    assert get_document(connection, document.id) == document
    chunks = get_document_chunks(connection, document.id)
    assert [chunk.text for chunk in chunks] == ["First passage.", "Second passage."]
    assert [chunk.page_number for chunk in chunks] == [1, 2]
    assert all(chunk.document_id == document.id for chunk in chunks)


def test_failed_chunk_insert_rolls_back_entire_document(db_connection):
    connection, _ = db_connection
    duplicate = DocumentChunk(chunk_index=0, page_number=1, text="Duplicate index.")
    with pytest.raises(psycopg.errors.UniqueViolation):
        create_document(connection, "broken.pdf", 1, [sample_chunks()[0], duplicate], sample_embeddings())

    assert connection.execute("SELECT count(*) AS total FROM documents").fetchone()["total"] == 0
    assert connection.execute("SELECT count(*) AS total FROM chunks").fetchone()["total"] == 0


def test_missing_document_has_no_chunks(db_connection):
    connection, _ = db_connection
    assert get_document(connection, -1) is None
    assert get_document_chunks(connection, -1) == []


def test_deleting_document_also_deletes_chunks(db_connection):
    connection, _ = db_connection
    document = create_document(connection, "example.pdf", 2, sample_chunks(), sample_embeddings())
    connection.execute("DELETE FROM documents WHERE id = %s", (document.id,))
    assert get_document_chunks(connection, document.id) == []


def test_pgvector_column_accepts_vectors(db_connection):
    connection, _ = db_connection
    document = create_document(connection, "example.pdf", 2, sample_chunks(), sample_embeddings())
    connection.execute(
        "UPDATE chunks SET embedding = %s::vector WHERE document_id = %s",
        (json.dumps([0.1] * 1024), document.id),
    )
    row = connection.execute(
        "SELECT vector_dims(embedding) AS dimensions FROM chunks LIMIT 1"
    ).fetchone()
    assert row["dimensions"] == 1024
    assert check_database(Settings()) is True


def test_pgvector_rejects_incompatible_dimensions(db_connection):
    connection, _ = db_connection
    document = create_document(connection, "example.pdf", 2, sample_chunks(), sample_embeddings())
    with pytest.raises(psycopg.errors.DataException):
        connection.execute(
            "UPDATE chunks SET embedding = %s::vector WHERE document_id = %s",
            ("[0.1,0.2,0.3]", document.id),
        )


@pytest.mark.parametrize("old_dimensions", [1024, 3])
def test_init_preserves_existing_data_or_rolls_back(db_connection, old_dimensions):
    connection, _ = db_connection
    connection.execute("ALTER TABLE chunks ALTER COLUMN embedding TYPE VECTOR")
    document = create_document(connection, "existing.pdf", 2, sample_chunks(), sample_embeddings())
    connection.execute(
        "UPDATE chunks SET embedding = %s::vector WHERE document_id = %s",
        (json.dumps([0.1] * old_dimensions), document.id),
    )
    connection.commit()

    schema_file = Path(__file__).resolve().parents[1] / "sql" / "001_init.sql"
    if old_dimensions == 1024:
        connection.execute(schema_file.read_text())
    else:
        with pytest.raises(psycopg.errors.DataException):
            connection.execute(schema_file.read_text())
        connection.rollback()

    assert get_document(connection, document.id) is not None
    row = connection.execute(
        "SELECT vector_dims(embedding) AS dimensions FROM chunks LIMIT 1"
    ).fetchone()
    assert row["dimensions"] == old_dimensions
    column = connection.execute(
        """SELECT atttypmod FROM pg_attribute
           WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"""
    ).fetchone()
    assert column["atttypmod"] == (1024 if old_dimensions == 1024 else -1)


def test_database_rejects_invalid_page_count(db_connection):
    connection, _ = db_connection
    with pytest.raises(psycopg.errors.CheckViolation):
        create_document(connection, "invalid.pdf", 0, sample_chunks(), sample_embeddings())
    assert get_document(connection, -1) is None


@pytest.mark.parametrize("ready", [True, False])
def test_database_health_status(client, monkeypatch, ready):
    monkeypatch.setattr("app.main.check_database", lambda settings: ready)
    response = client.get("/health/db")
    assert response.status_code == (200 if ready else 503)


def test_database_health_hides_connection_errors(client, monkeypatch):
    def fail(settings):
        raise psycopg.OperationalError("Connection information must not be exposed.")

    monkeypatch.setattr("app.main.check_database", fail)
    response = client.get("/health/db")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable or not initialized."}


def test_connection_failure_traceback_hides_driver_details(monkeypatch):
    def fail(**kwargs):
        raise psycopg.OperationalError("password=private-database-password")

    monkeypatch.setattr("app.database.psycopg.connect", fail)
    settings = Settings(_env_file=None, postgres_password="private-database-password")
    with pytest.raises(psycopg.OperationalError) as error:
        get_connection(settings)
    displayed = "".join(traceback.format_exception(error.value))
    assert "private-database-password" not in displayed
    assert "Check database availability and settings" in displayed
