from contextlib import nullcontext
from datetime import datetime, timezone
from unittest.mock import Mock

import psycopg
import pytest

from app.embeddings import EmbeddingError, EmbeddingResult
from app.repository import create_document, search_chunks
from app.schemas import DocumentChunk, SearchMatch, StoredDocument


def vector(first=1.0, second=0.0):
    return [first, second] + [0.0] * 1022


@pytest.fixture
def retrieval_mocks(monkeypatch):
    document = StoredDocument(
        id=7, filename="internship.pdf", page_count=2,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    mocks = {
        "get_connection": Mock(side_effect=lambda settings: nullcontext(object())),
        "get_document": Mock(return_value=document),
        "embed_query": Mock(return_value=EmbeddingResult(embeddings=[vector()], total_tokens=4)),
        "search_chunks": Mock(return_value=[SearchMatch(
            chunk_id=21, chunk_index=0, page_number=1,
            text="The internship lasts six months.", similarity=0.9,
        )]),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(f"app.retrieval.{name}", mock)
    return mocks


def test_search_response_and_trimmed_question(client, retrieval_mocks):
    response = client.post("/search", json={
        "document_id": 7, "question": "  How long is the internship?  ", "top_k": 2,
    })
    assert response.status_code == 200
    assert response.json() == {
        "document_id": 7, "filename": "internship.pdf",
        "question": "How long is the internship?", "embedding_tokens": 4,
        "matches": [{
            "chunk_id": 21, "chunk_index": 0, "page_number": 1,
            "text": "The internship lasts six months.", "similarity": 0.9,
        }],
    }
    assert retrieval_mocks["embed_query"].call_args.args[0] == "How long is the internship?"
    assert retrieval_mocks["search_chunks"].call_args.args[1:] == (7, vector(), 2)


@pytest.mark.parametrize("changes", [
    {"document_id": 0}, {"document_id": -1}, {"question": ""},
    {"question": " \n\t"}, {"question": "x" * 2001},
    {"top_k": 0}, {"top_k": 11}, {"question": None},
])
def test_invalid_search_never_calls_voyage(client, retrieval_mocks, changes):
    body = {"document_id": 7, "question": "A question?", **changes}
    assert client.post("/search", json=body).status_code == 422
    retrieval_mocks["embed_query"].assert_not_called()
    retrieval_mocks["get_connection"].assert_not_called()


def test_missing_document_does_not_spend_tokens(client, retrieval_mocks):
    retrieval_mocks["get_document"].return_value = None
    assert client.post("/search", json={"document_id": 99, "question": "Question?"}).status_code == 404
    retrieval_mocks["embed_query"].assert_not_called()


def test_deleted_during_embedding_returns_404(client, retrieval_mocks):
    retrieval_mocks["get_document"].side_effect = [
        retrieval_mocks["get_document"].return_value, None,
    ]
    response = client.post("/search", json={"document_id": 7, "question": "Question?"})
    assert response.status_code == 404
    retrieval_mocks["search_chunks"].assert_not_called()


@pytest.mark.parametrize("operation", ["get_document", "search_chunks"])
def test_database_failure_is_safe(client, retrieval_mocks, operation):
    retrieval_mocks[operation].side_effect = psycopg.OperationalError("Private details.")
    response = client.post("/search", json={"document_id": 7, "question": "Question?"})
    assert response.status_code == 503
    assert "Private" not in response.text
    if operation == "get_document":
        retrieval_mocks["embed_query"].assert_not_called()


def test_embedding_failure_is_safe(client, retrieval_mocks):
    retrieval_mocks["embed_query"].side_effect = EmbeddingError("Private Voyage details.")
    response = client.post("/search", json={"document_id": 7, "question": "Question?"})
    assert response.status_code == 502
    assert "Private" not in response.text
    retrieval_mocks["search_chunks"].assert_not_called()


def test_no_searchable_chunks_returns_empty_list(client, retrieval_mocks):
    retrieval_mocks["search_chunks"].return_value = []
    response = client.post("/search", json={"document_id": 7, "question": "Question?"})
    assert response.status_code == 200
    assert response.json()["matches"] == []
    assert retrieval_mocks["search_chunks"].call_args.args[-1] == 3


@pytest.mark.parametrize("embedding", [[0.0] * 1024, [1.0, 2.0], [float("nan")] * 1024])
def test_invalid_query_vector_is_rejected_before_sql(embedding):
    with pytest.raises(ValueError):
        search_chunks(None, 7, embedding, 3)


def seed_document(connection, filename="internship.pdf"):
    chunks = [
        DocumentChunk(chunk_index=0, page_number=1, text="The internship lasts six months."),
        DocumentChunk(chunk_index=1, page_number=2, text="Applications close in January."),
        DocumentChunk(chunk_index=2, page_number=3, text="Work is based in Paris."),
    ]
    return create_document(
        connection, filename, 3, chunks,
        [vector(1, 0), vector(1, 1), vector(0, 1)],
    )


def test_cosine_ranking_and_document_isolation(db_connection):
    connection, _ = db_connection
    selected = seed_document(connection)
    seed_document(connection, "other.pdf")
    matches = search_chunks(connection, selected.id, vector(), 2)
    assert [match.chunk_index for match in matches] == [0, 1]
    assert matches[0].similarity == pytest.approx(1.0)
    assert matches[1].similarity == pytest.approx(2 ** -0.5)
    assert [match.page_number for match in matches] == [1, 2]


def test_null_and_zero_vectors_are_not_searched(db_connection):
    connection, _ = db_connection
    selected = seed_document(connection)
    connection.execute(
        "UPDATE chunks SET embedding = NULL WHERE document_id = %s AND chunk_index = 0",
        (selected.id,),
    )
    connection.execute(
        "UPDATE chunks SET embedding = %s::vector WHERE document_id = %s AND chunk_index = 1",
        ("[" + ",".join(["0"] * 1024) + "]", selected.id),
    )
    matches = search_chunks(connection, selected.id, vector(), 10)
    assert [match.chunk_index for match in matches] == [2]


def test_search_api_with_real_pgvector(library_client, db_connection, monkeypatch):
    connection, _ = db_connection
    selected = seed_document(connection)
    seed_document(connection, "other.pdf")
    connection.commit()
    mock = Mock(return_value=EmbeddingResult(embeddings=[vector()], total_tokens=4))
    monkeypatch.setattr("app.retrieval.embed_query", mock)

    response = library_client.post("/search", json={
        "document_id": selected.id, "question": "How long is the internship?", "top_k": 2,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == selected.id
    assert body["filename"] == "internship.pdf"
    assert [match["text"] for match in body["matches"]] == [
        "The internship lasts six months.", "Applications close in January.",
    ]
    assert "embedding" not in body["matches"][0]
    assert len(body["matches"]) == 2
