import pytest
import psycopg

from app.config import Settings, get_settings
from app.embeddings import EmbeddingError
from app.main import app


def upload(client, content, filename="document.pdf", content_type="application/pdf"):
    return client.post(
        "/documents", files={"file": (filename, content, content_type)}
    )


def test_extracts_text_and_preserves_blank_page_numbers(client, make_pdf):
    response = upload(client, make_pdf(["First page.", "", "Third page."]))

    assert response.status_code == 201
    assert response.json() == {
        "id": 123,
        "created_at": "2026-01-01T00:00:00Z",
        "embedding_model": "voyage-4-lite",
        "embedding_tokens": 20,
        "filename": "document.pdf",
        "page_count": 3,
        "pages": [
            {"page_number": 1, "text": "First page."},
            {"page_number": 2, "text": ""},
            {"page_number": 3, "text": "Third page."},
        ],
        "chunk_count": 2,
        "chunks": [
            {"chunk_index": 0, "page_number": 1, "text": "First page."},
            {"chunk_index": 1, "page_number": 3, "text": "Third page."},
        ],
    }


def test_accepts_uppercase_extension_and_generic_mime_type(client, make_pdf):
    response = upload(
        client, make_pdf(["Readable text."]), "DOCUMENT.PDF", "application/octet-stream"
    )
    assert response.status_code == 201


def test_upload_uses_configured_chunk_size_and_overlap(client, make_pdf):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, chunk_size=10, chunk_overlap=3
    )
    response = upload(client, make_pdf(["abcdefghijklmnopq"]))
    assert response.status_code == 201
    data = response.json()
    assert data["chunk_count"] == 2
    assert data["chunks"] == [
        {"chunk_index": 0, "page_number": 1, "text": "abcdefghij"},
        {"chunk_index": 1, "page_number": 1, "text": "hijklmnopq"},
    ]


def test_rejects_non_pdf_extension(client, make_pdf):
    response = upload(client, make_pdf(["Text."]), "notes.txt", "text/plain")
    assert response.status_code == 415


def test_rejects_empty_file(client):
    response = upload(client, b"")
    assert response.status_code == 400
    assert response.json()["detail"] == "The uploaded file is empty."


@pytest.mark.parametrize("content", [b"This is not a PDF.", b"%PDF-1.7\nbroken"])
def test_rejects_fake_or_damaged_pdf(client, content):
    response = upload(client, content)
    assert response.status_code == 422
    assert "detail" in response.json()


def test_rejects_oversized_file(client):
    response = upload(client, b"%PDF-" + b"x" * (1024 * 1024))
    assert response.status_code == 413
    assert "1 MiB" in response.json()["detail"]


def test_rejects_too_many_pages(client, make_pdf):
    response = upload(client, make_pdf(["Page."] * 4))
    assert response.status_code == 413
    assert "3 pages" in response.json()["detail"]


def test_rejects_pdf_without_text(client, make_pdf):
    response = upload(client, make_pdf(["", ""]))
    assert response.status_code == 422
    assert "no extractable text" in response.json()["detail"]


def test_rejects_encrypted_pdf(client, make_pdf):
    response = upload(client, make_pdf(["Private text."], password="secret"))
    assert response.status_code == 422
    assert response.json()["detail"] == "Encrypted PDFs are not supported."


def test_requires_file(client):
    response = client.post("/documents")
    assert response.status_code == 422


def test_health_and_api_schema(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "multipart/form-data" in schema["paths"]["/documents"]["post"]["requestBody"]["content"]


def test_indexes_chunks_with_their_matching_vectors(client, make_pdf, upload_mocks):
    response = upload(client, make_pdf(["First page.", "Second page."]))
    assert response.status_code == 201
    assert upload_mocks["embed_documents"].call_args.args[0] == ["First page.", "Second page."]
    arguments = upload_mocks["create_document"].call_args.args
    assert [chunk.text for chunk in arguments[3]] == ["First page.", "Second page."]
    assert len(arguments[4]) == 2
    assert all(len(vector) == 1024 for vector in arguments[4])


def test_embedding_failure_does_not_save_document(client, make_pdf, upload_mocks):
    upload_mocks["embed_documents"].side_effect = EmbeddingError("Private provider details.")
    response = upload(client, make_pdf(["Text."]))
    assert response.status_code == 502
    assert "Private" not in response.text
    upload_mocks["create_document"].assert_not_called()
    upload_mocks["get_connection"].assert_not_called()


@pytest.mark.parametrize("failure", [False, psycopg.OperationalError("Private database details.")])
def test_unavailable_database_avoids_spending_tokens(client, make_pdf, upload_mocks, failure):
    if failure is False:
        upload_mocks["check_database"].return_value = False
    else:
        upload_mocks["check_database"].side_effect = failure
    response = upload(client, make_pdf(["Text."]))
    assert response.status_code == 503
    assert "Private" not in response.text
    upload_mocks["embed_documents"].assert_not_called()
    upload_mocks["create_document"].assert_not_called()


def test_save_failure_returns_generic_error(client, make_pdf, upload_mocks):
    upload_mocks["create_document"].side_effect = psycopg.OperationalError("Private details.")
    response = upload(client, make_pdf(["Text."]))
    assert response.status_code == 503
    assert "Private" not in response.text
