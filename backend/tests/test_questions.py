from unittest.mock import Mock

import psycopg
import pytest

from app.config import Settings, get_settings
from app.embeddings import EmbeddingError, EmbeddingResult
from app.generation import GenerationError, GenerationResult, INSUFFICIENT_CONTEXT
from app.main import app
from app.retrieval import DocumentNotFoundError
from app.schemas import GenerationUsage, SearchMatch, SearchResponse


@pytest.fixture
def question_mocks(client, monkeypatch):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, groq_api_key="test-groq-key")
    retrieval = Mock(return_value=SearchResponse(
        document_id=7, filename="internship.pdf", question="How long is the internship?",
        embedding_tokens=4, matches=[
            SearchMatch(chunk_id=42, chunk_index=0, page_number=3,
                        text="The internship lasts six months.", similarity=0.8),
            SearchMatch(chunk_id=43, chunk_index=1, page_number=4,
                        text="Work is based in Paris.", similarity=0.5),
        ],
    ))
    generation = Mock(return_value=GenerationResult(
        answer="The internship lasts six months. [1]", answerable=True, source_ids=[1],
        usage=GenerationUsage(prompt_tokens=200, completion_tokens=20, total_tokens=220),
    ))
    monkeypatch.setattr("app.questions.retrieve_passages", retrieval)
    monkeypatch.setattr("app.questions.generate_answer", generation)
    return retrieval, generation


def ask(client):
    return client.post("/questions", json={"document_id": 7, "question": "How long is the internship?"})


def test_answer_uses_only_cited_database_sources(client, question_mocks):
    response = ask(client)
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "The internship lasts six months. [1]"
    assert body["answerable"] is True
    assert body["llm_model"] == "qwen/qwen3.8-27b"
    assert body["embedding_tokens"] == 4
    assert body["llm_usage"]["total_tokens"] == 220
    assert body["sources"] == [{
        "source_id": 1, "document_id": 7, "filename": "internship.pdf",
        "chunk_id": 42, "chunk_index": 0, "page_number": 3,
        "text": "The internship lasts six months.", "similarity": 0.8,
    }]


def test_source_ids_are_not_renumbered_after_filtering(client, question_mocks):
    _, generation = question_mocks
    generation.return_value.answer = "Work is based in Paris. [2]"
    generation.return_value.source_ids = [2]
    body = ask(client).json()
    assert body["sources"][0]["source_id"] == 2
    assert body["sources"][0]["chunk_id"] == 43
    assert body["sources"][0]["page_number"] == 4


def test_missing_key_does_not_spend_voyage_tokens(client, question_mocks):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, groq_api_key="")
    response = ask(client)
    assert response.status_code == 503
    question_mocks[0].assert_not_called()
    question_mocks[1].assert_not_called()


def test_no_context_skips_generation(client, question_mocks):
    retrieval, generation = question_mocks
    retrieval.return_value.matches = []
    body = ask(client).json()
    assert body["answer"] == INSUFFICIENT_CONTEXT
    assert body["answerable"] is False
    assert body["sources"] == []
    assert body["llm_usage"] is None
    assert body["llm_model"] is None
    generation.assert_not_called()


def test_model_abstention_returns_no_sources(client, question_mocks):
    _, generation = question_mocks
    generation.return_value = GenerationResult(
        answer=INSUFFICIENT_CONTEXT, answerable=False, source_ids=[],
        usage=GenerationUsage(prompt_tokens=200, completion_tokens=20, total_tokens=220),
    )
    body = ask(client).json()
    assert body["answerable"] is False
    assert body["sources"] == []
    assert body["llm_usage"]["total_tokens"] == 220


def test_context_budget_matches_returned_source_text(client, question_mocks):
    retrieval, generation = question_mocks
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, groq_api_key="test-groq-key", llm_max_context_chars=500,
    )
    retrieval.return_value.matches[0].text = "a" * 700
    body = ask(client).json()
    sent_sources = generation.call_args.args[1]
    assert len(sent_sources) == 1
    assert sent_sources[0].text == "a" * 500
    assert body["sources"][0]["text"] == sent_sources[0].text


@pytest.mark.parametrize("changes", [{"question": " "}, {"top_k": 11}, {"document_id": 0}])
def test_invalid_question_does_not_call_providers(client, question_mocks, changes):
    body = {"document_id": 7, "question": "Question?", **changes}
    assert client.post("/questions", json=body).status_code == 422
    question_mocks[0].assert_not_called()
    question_mocks[1].assert_not_called()


@pytest.mark.parametrize("error,status", [
    (DocumentNotFoundError("Private details."), 404),
    (EmbeddingError("Private details."), 502),
    (psycopg.OperationalError("Private details."), 503),
])
def test_retrieval_errors_are_safe(client, question_mocks, error, status):
    question_mocks[0].side_effect = error
    response = ask(client)
    assert response.status_code == status
    assert "Private" not in response.text
    question_mocks[1].assert_not_called()


def test_generation_error_is_safe(client, question_mocks):
    question_mocks[1].side_effect = GenerationError("Private Groq details.")
    response = ask(client)
    assert response.status_code == 502
    assert "Private" not in response.text


def test_full_question_pipeline_with_postgres(library_client, db_connection, make_pdf, monkeypatch):
    # Use real extraction, storage, retrieval, prompt building, and citation checks.
    # Only the two external providers are simulated.
    import httpx
    import json

    app.dependency_overrides[get_settings] = lambda: Settings(groq_api_key="test-groq-key")
    document = library_client.post("/documents", files={
        "file": ("internship.pdf", make_pdf(["The internship lasts six months."]), "application/pdf")
    }).json()
    monkeypatch.setattr("app.retrieval.embed_query", Mock(return_value=EmbeddingResult(
        embeddings=[[0.1] * 1024], total_tokens=4,
    )))
    real_client = httpx.Client

    def handler(request):
        context = json.loads(json.loads(request.content)["messages"][1]["content"])
        assert context["sources"][0]["text"] == "The internship lasts six months."
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
                "answer": "The internship lasts six months. [1]", "answerable": True,
                "source_ids": [1],
            })}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220},
        })

    monkeypatch.setattr("app.generation.httpx.Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    response = library_client.post("/questions", json={
        "document_id": document["id"], "question": "How long is the internship?",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["answerable"] is True
    assert body["sources"][0]["document_id"] == document["id"]
    assert body["sources"][0]["filename"] == "internship.pdf"
    assert body["sources"][0]["page_number"] == 1
