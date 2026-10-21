import json
from unittest.mock import Mock

import psycopg
import pytest

from app.embeddings import EmbeddingError
from app.repository import create_document
from app.schemas import DocumentChunk


def upload(client, make_pdf, pages=None, filename="example.pdf"):
    return client.post(
        "/documents",
        files={"file": (filename, make_pdf(pages or ["Example text."]), "application/pdf")},
    )


def test_api_persists_matching_chunks_and_embeddings(library_client, db_connection, make_pdf):
    response = upload(library_client, make_pdf, ["First passage.", "Second passage."])
    assert response.status_code == 201
    document = response.json()
    assert document["chunk_count"] == 2
    connection, _ = db_connection
    rows = connection.execute(
        """SELECT chunk_index, page_number, text, embedding::text AS vector
           FROM chunks WHERE document_id = %s ORDER BY chunk_index""",
        (document["id"],),
    ).fetchall()
    assert [row["text"] for row in rows] == ["First passage.", "Second passage."]
    assert [row["page_number"] for row in rows] == [1, 2]
    assert [len(json.loads(row["vector"])) for row in rows] == [1024, 1024]
    assert [json.loads(row["vector"])[0] for row in rows] == [0.1, 0.2]


def test_shared_library_listing_and_pagination(library_client, make_pdf):
    assert library_client.get("/documents").json() == []
    first = upload(library_client, make_pdf).json()
    second = upload(library_client, make_pdf).json()
    assert first["id"] != second["id"]

    documents = library_client.get("/documents").json()
    assert [document["id"] for document in documents] == [second["id"], first["id"]]
    assert documents[0] == {
        "id": second["id"], "filename": "example.pdf", "page_count": 1,
        "created_at": second["created_at"], "chunk_count": 1,
    }
    response = library_client.get("/documents", params={"limit": 1, "offset": 1})
    assert [document["id"] for document in response.json()] == [first["id"]]


def test_delete_removes_metadata_chunks_and_vectors(library_client, db_connection, make_pdf):
    document = upload(library_client, make_pdf).json()
    response = library_client.delete(f"/documents/{document['id']}")
    assert response.status_code == 204
    assert response.content == b""
    assert library_client.get("/documents").json() == []
    connection, _ = db_connection
    assert connection.execute("SELECT count(*) AS total FROM chunks").fetchone()["total"] == 0
    assert library_client.delete(f"/documents/{document['id']}").status_code == 404


def test_voyage_failure_leaves_library_empty(library_client, db_connection, make_pdf, upload_mocks):
    upload_mocks["embed_documents"].side_effect = EmbeddingError("A later batch failed.")
    response = upload(library_client, make_pdf)
    assert response.status_code == 502
    assert library_client.get("/documents").json() == []
    connection, _ = db_connection
    assert connection.execute("SELECT count(*) AS total FROM chunks").fetchone()["total"] == 0


@pytest.mark.parametrize("vectors", [[], [[0.1] * 3], [[float("nan")] * 1024]])
def test_repository_rejects_inconsistent_vectors_before_writing(vectors):
    chunks = [DocumentChunk(chunk_index=0, page_number=1, text="A passage.")]
    with pytest.raises(ValueError):
        create_document(None, "example.pdf", 1, chunks, vectors)


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_rejects_invalid_pagination(client, query, upload_mocks):
    assert client.get(f"/documents?{query}").status_code == 422
    upload_mocks["get_connection"].assert_not_called()


@pytest.mark.parametrize("document_id", [0, -1, "invalid"])
def test_rejects_invalid_document_id(client, document_id, upload_mocks):
    assert client.delete(f"/documents/{document_id}").status_code == 422
    upload_mocks["get_connection"].assert_not_called()


def test_missing_document_returns_404(client, monkeypatch):
    monkeypatch.setattr("app.main.delete_document", Mock(return_value=False))
    response = client.delete("/documents/99")
    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found."}


@pytest.mark.parametrize("operation", ["list_documents", "delete_document"])
def test_library_database_errors_hide_connection_details(client, monkeypatch, operation):
    monkeypatch.setattr(
        f"app.main.{operation}", Mock(side_effect=psycopg.OperationalError("Private details."))
    )
    response = client.get("/documents") if operation == "list_documents" else client.delete("/documents/1")
    assert response.status_code == 503
    assert "Private" not in response.text
