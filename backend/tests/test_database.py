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


def test_saves_document_and_chunks_and_commits(db_connection):
    connection, schema = db_connection
    document = create_document(connection, "Intern's guide.pdf", 2, sample_chunks())

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
        create_document(connection, "broken.pdf", 1, [sample_chunks()[0], duplicate])

    assert connection.execute("SELECT count(*) AS total FROM documents").fetchone()["total"] == 0
    assert connection.execute("SELECT count(*) AS total FROM chunks").fetchone()["total"] == 0


def test_missing_document_has_no_chunks(db_connection):
    connection, _ = db_connection
    assert get_document(connection, -1) is None
    assert get_document_chunks(connection, -1) == []


def test_deleting_document_also_deletes_chunks(db_connection):
    connection, _ = db_connection
    document = create_document(connection, "example.pdf", 2, sample_chunks())
    connection.execute("DELETE FROM documents WHERE id = %s", (document.id,))
    assert get_document_chunks(connection, document.id) == []


def test_pgvector_column_accepts_vectors(db_connection):
    connection, _ = db_connection
    document = create_document(connection, "example.pdf", 2, sample_chunks())
    connection.execute(
        "UPDATE chunks SET embedding = %s::vector WHERE document_id = %s",
        ("[0.1,0.2,0.3]", document.id),
    )
    row = connection.execute(
        "SELECT vector_dims(embedding) AS dimensions FROM chunks LIMIT 1"
    ).fetchone()
    assert row["dimensions"] == 3
    assert check_database(Settings()) is True


def test_database_rejects_invalid_page_count(db_connection):
    connection, _ = db_connection
    with pytest.raises(psycopg.errors.CheckViolation):
        create_document(connection, "invalid.pdf", 0, sample_chunks())
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
