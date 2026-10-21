from unittest.mock import Mock

import pytest

from app.auth import require_admin_key
from app.config import Settings, get_settings
from app.main import app


@pytest.fixture
def auth_client(client):
    app.dependency_overrides.pop(require_admin_key)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, admin_api_key="test-admin-secret",
    )
    return client


def mutate(client, operation, make_pdf, headers=None):
    if operation == "upload":
        return client.post("/documents", headers=headers, files={
            "file": ("example.pdf", make_pdf(["Example text."]), "application/pdf"),
        })
    return client.delete("/documents/1", headers=headers)


@pytest.mark.parametrize("operation", ["upload", "delete"])
@pytest.mark.parametrize("key", [None, "", "wrong-key", "non-ascii-\u00e9"])
def test_unauthorized_mutations_do_not_process_data(
    auth_client, make_pdf, upload_mocks, monkeypatch, operation, key
):
    deletion = Mock()
    extraction = Mock()
    monkeypatch.setattr("app.main.delete_document", deletion)
    monkeypatch.setattr("app.main.extract_pdf_pages", extraction)
    headers = {"X-Admin-Key": key.encode("utf-8")} if key is not None else {}
    response = mutate(auth_client, operation, make_pdf, headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing administrator key."}
    for mock in upload_mocks.values():
        mock.assert_not_called()
    deletion.assert_not_called()
    extraction.assert_not_called()


@pytest.mark.parametrize("operation", ["upload", "delete"])
def test_missing_server_key_disables_mutations(auth_client, make_pdf, operation, upload_mocks):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, admin_api_key="")
    response = mutate(auth_client, operation, make_pdf, {"X-Admin-Key": "any-key"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Administrator access is not configured."}
    upload_mocks["embed_documents"].assert_not_called()
    upload_mocks["get_connection"].assert_not_called()


def test_admin_can_upload(auth_client, make_pdf):
    response = mutate(auth_client, "upload", make_pdf, {"X-Admin-Key": "test-admin-secret"})
    assert response.status_code == 201
    assert response.json()["id"] == 123
    assert "test-admin-secret" not in response.text


def test_admin_can_delete(auth_client, monkeypatch, make_pdf):
    deletion = Mock(return_value=True)
    monkeypatch.setattr("app.main.delete_document", deletion)
    response = mutate(auth_client, "delete", make_pdf, {"X-Admin-Key": "test-admin-secret"})
    assert response.status_code == 204
    deletion.assert_called_once()


def test_query_parameter_cannot_replace_header(auth_client, make_pdf):
    response = auth_client.post("/documents?ADMIN_API_KEY=test-admin-secret", files={
        "file": ("example.pdf", make_pdf(["Example text."]), "application/pdf"),
    })
    assert response.status_code == 401


def test_library_and_health_are_public(auth_client, monkeypatch):
    monkeypatch.setattr("app.main.list_documents", Mock(return_value=[]))
    assert auth_client.get("/documents").status_code == 200
    assert auth_client.get("/health").status_code == 200
    assert auth_client.get("/docs").status_code == 200


def test_only_mutations_require_admin_in_api_schema(auth_client):
    schema = auth_client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["AdminKey"]["name"] == "X-Admin-Key"
    assert schema["paths"]["/documents"]["post"]["security"] == [{"AdminKey": []}]
    assert schema["paths"]["/documents/{document_id}"]["delete"]["security"] == [{"AdminKey": []}]
    for path, method in [("/documents", "get"), ("/search", "post"), ("/questions", "post")]:
        assert not schema["paths"][path][method].get("security")


def test_admin_key_is_masked_in_settings():
    settings = Settings(_env_file=None, admin_api_key="test-admin-secret")
    assert "test-admin-secret" not in repr(settings)


def test_admin_auth_with_real_library(library_client, make_pdf):
    app.dependency_overrides.pop(require_admin_key)
    app.dependency_overrides[get_settings] = lambda: Settings(admin_api_key="test-admin-secret")
    headers = {"X-Admin-Key": "test-admin-secret"}
    content = make_pdf(["A public demonstration document."])
    files = {"file": ("example.pdf", content, "application/pdf")}
    assert library_client.post("/documents", files=files).status_code == 401
    assert library_client.get("/documents").json() == []
    response = library_client.post("/documents", files=files, headers=headers)
    assert response.status_code == 201
    document_id = response.json()["id"]
    assert library_client.delete(f"/documents/{document_id}").status_code == 401
    assert len(library_client.get("/documents").json()) == 1
    assert library_client.delete(f"/documents/{document_id}", headers=headers).status_code == 204
    assert library_client.get("/documents").json() == []
