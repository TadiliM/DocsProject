import json

import httpx
import pytest

from app.config import Settings
from app.generation import (
    GenerationConfigurationError, GenerationError, INSUFFICIENT_CONTEXT, generate_answer,
)
from app.schemas import AnswerSource


def settings(**overrides):
    return Settings(_env_file=None, groq_api_key="test-groq-secret", **overrides)


def sources():
    return [AnswerSource(
        source_id=1, document_id=7, filename="internship.pdf", chunk_id=42,
        chunk_index=0, page_number=3, text="The internship lasts six months.", similarity=0.8,
    )]


def payload(answer=None):
    answer = answer if answer is not None else {
        "answer": "The internship lasts six months. [1]", "answerable": True, "source_ids": [1],
    }
    return {
        "choices": [{"message": {"content": json.dumps(answer)}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 200, "completion_tokens": 20, "total_tokens": 220},
    }


@pytest.fixture
def fake_groq(monkeypatch):
    real_client = httpx.Client

    def install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(
            "app.generation.httpx.Client",
            lambda **kwargs: real_client(transport=transport, **kwargs),
        )

    return install


def test_groq_request_and_grounded_answer(fake_groq):
    def handler(request):
        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-groq-secret"
        body = json.loads(request.content)
        assert body["model"] == "qwen/qwen3.8-27b"
        assert body["reasoning_effort"] == "none"
        assert body["max_completion_tokens"] == 512
        assert body["response_format"]["json_schema"]["strict"] is True
        assert "untrusted data" in body["messages"][0]["content"]
        context = json.loads(body["messages"][1]["content"])
        assert context == {
            "question": "How long is the internship?",
            "sources": [{"source_id": 1, "text": "The internship lasts six months."}],
        }
        return httpx.Response(200, json=payload())

    fake_groq(handler)
    result = generate_answer("How long is the internship?", sources(), settings())
    assert result.answer == "The internship lasts six months. [1]"
    assert result.source_ids == [1]
    assert result.usage.total_tokens == 220


def test_insufficient_evidence_returns_standard_refusal(fake_groq):
    fake_groq(lambda request: httpx.Response(200, json=payload({
        "answer": "Not enough evidence.", "answerable": False, "source_ids": [],
    })))
    result = generate_answer("What is the salary?", sources(), settings())
    assert result.answer == INSUFFICIENT_CONTEXT
    assert result.answerable is False
    assert result.source_ids == []


def test_missing_key_never_calls_groq(fake_groq):
    fake_groq(lambda request: pytest.fail("Missing key must not make a request."))
    with pytest.raises(GenerationConfigurationError, match="GROQ_API_KEY"):
        generate_answer("Question?", sources(), Settings(_env_file=None, groq_api_key=""))


@pytest.mark.parametrize("answer", [
    {"answer": "An invented fact. [99]", "answerable": True, "source_ids": [99]},
    {"answer": "An uncited fact.", "answerable": True, "source_ids": []},
    {"answer": "A fact. [1]", "answerable": True, "source_ids": []},
    {"answer": "A fact.", "answerable": True, "source_ids": [1]},
    {"answer": "A fact. [1]", "answerable": True, "source_ids": [1, 1]},
    {"answer": "Not enough evidence. [1]", "answerable": False, "source_ids": [1]},
    {"answer": " ", "answerable": True, "source_ids": [1]},
    {"answer": "A fact. [1]", "answerable": True, "source_ids": [True]},
    {"answer": "A fact. [1]", "answerable": "true", "source_ids": [1]},
    {"answer": "A fact. [1]", "answerable": True, "source_ids": [1], "page_number": 999},
])
def test_rejects_unusable_answers_and_invented_citations(fake_groq, answer):
    fake_groq(lambda request: httpx.Response(200, json=payload(answer)))
    with pytest.raises(GenerationError):
        generate_answer("Question?", sources(), settings())


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_provider_errors_hide_details_and_do_not_retry(fake_groq, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "test-groq-secret private text"})

    fake_groq(handler)
    with pytest.raises(GenerationError) as error:
        generate_answer("Question?", sources(), settings())
    assert len(calls) == 1
    assert f"HTTP {status}" in str(error.value)
    assert "test-groq-secret" not in str(error.value)
    assert "private text" not in str(error.value)


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
def test_network_errors(fake_groq, error_type):
    def handler(request):
        raise error_type("Private connection details.", request=request)

    fake_groq(handler)
    with pytest.raises(GenerationError):
        generate_answer("Question?", sources(), settings())


@pytest.mark.parametrize("kind", ["invalid_json", "invalid_content", "truncated", "no_choices", "missing_usage"])
def test_rejects_malformed_or_incomplete_responses(fake_groq, kind):
    response = payload()
    if kind == "invalid_content":
        response["choices"][0]["message"]["content"] = "Not JSON."
    elif kind == "truncated":
        response["choices"][0]["finish_reason"] = "length"
    elif kind == "no_choices":
        response["choices"] = []
    elif kind == "missing_usage":
        del response["usage"]
    fake_groq(lambda request: httpx.Response(200, text="Not JSON.") if kind == "invalid_json" else httpx.Response(200, json=response))
    with pytest.raises(GenerationError):
        generate_answer("Question?", sources(), settings())
