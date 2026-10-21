import pytest

from app.config import Settings, get_settings
from app.main import app


def upload(client, content, filename="document.pdf", content_type="application/pdf"):
    return client.post(
        "/documents", files={"file": (filename, content, content_type)}
    )


def test_extracts_text_and_preserves_blank_page_numbers(client, make_pdf):
    response = upload(client, make_pdf(["First page.", "", "Third page."]))

    assert response.status_code == 200
    assert response.json() == {
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
    assert response.status_code == 200


def test_upload_uses_configured_chunk_size_and_overlap(client, make_pdf):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, chunk_size=10, chunk_overlap=3
    )
    response = upload(client, make_pdf(["abcdefghijklmnopq"]))
    assert response.status_code == 200
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
