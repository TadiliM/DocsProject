import json

import httpx
import pytest

from app.config import Settings
from app.embeddings import EmbeddingError, embed_documents, embed_query


def settings(**overrides):
    return Settings(_env_file=None, voyage_api_key="test-secret-key", **overrides)


def payload(count=1):
    return {
        "data": [
            {"index": index, "embedding": [float(index + 1)] * 1024}
            for index in range(count)
        ],
        "usage": {"total_tokens": 7},
    }


@pytest.fixture
def fake_voyage(monkeypatch):
    real_client = httpx.Client

    def install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(
            "app.embeddings.httpx.Client",
            lambda **kwargs: real_client(transport=transport, **kwargs),
        )

    return install


def test_document_request_and_response_order(fake_voyage):
    def handler(request):
        assert str(request.url) == "https://api.voyageai.com/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer test-secret-key"
        assert json.loads(request.content) == {
            "input": ["First passage.", "Second passage."],
            "model": "voyage-4-lite",
            "input_type": "document",
            "output_dimension": 1024,
            "output_dtype": "float",
            "truncation": False,
        }
        response = payload(2)
        response["data"].reverse()
        return httpx.Response(200, json=response)

    fake_voyage(handler)
    result = embed_documents(["First passage.", "Second passage."], settings())
    assert result.model == "voyage-4-lite"
    assert result.dimensions == 1024
    assert [vector[0] for vector in result.embeddings] == [1.0, 2.0]
    assert result.total_tokens == 7


def test_query_uses_query_input_type(fake_voyage):
    def handler(request):
        body = json.loads(request.content)
        assert body["input_type"] == "query"
        assert body["input"] == ["How long is the internship?"]
        assert body["model"] == "voyage-4-lite"
        return httpx.Response(200, json=payload())

    fake_voyage(handler)
    result = embed_query("How long is the internship?", settings())
    assert len(result.embeddings) == 1
    assert len(result.embeddings[0]) == 1024


def test_batches_inputs_and_sums_token_usage(fake_voyage):
    batches = []

    def handler(request):
        texts = json.loads(request.content)["input"]
        batches.append(texts)
        response = payload(len(texts))
        for item, text in zip(response["data"], texts):
            item["embedding"] = [float(text)] * 1024
        return httpx.Response(200, json=response)

    fake_voyage(handler)
    result = embed_documents(["1", "2", "3", "4", "5"], settings(voyage_batch_size=2))
    assert batches == [["1", "2"], ["3", "4"], ["5"]]
    assert [vector[0] for vector in result.embeddings] == [1, 2, 3, 4, 5]
    assert result.total_tokens == 21


def test_missing_key_is_reported_without_a_network_call(fake_voyage):
    def unexpected_request(request):
        pytest.fail("A missing key must not trigger an HTTP request.")

    fake_voyage(unexpected_request)
    with pytest.raises(EmbeddingError, match="Set VOYAGE_API_KEY"):
        embed_documents(["Text."], Settings(_env_file=None, voyage_api_key=""))


def test_empty_input_needs_no_key_or_api_call(fake_voyage):
    fake_voyage(lambda request: pytest.fail("Empty input must not call Voyage."))
    result = embed_documents([], Settings(_env_file=None, voyage_api_key=""))
    assert result.embeddings == []
    assert result.total_tokens == 0


@pytest.mark.parametrize("texts", [[""], [" \n"], ["Valid", 123]])
def test_rejects_empty_or_invalid_texts_before_calling_api(fake_voyage, texts):
    fake_voyage(lambda request: pytest.fail("Invalid input must not call Voyage."))
    with pytest.raises(ValueError, match="non-empty text"):
        embed_documents(texts, settings())


@pytest.mark.parametrize(
    "status,message",
    [(401, "authentication"), (403, "authentication"), (429, "rate limit"),
     (400, "rejected"), (422, "rejected"), (500, "unavailable"), (503, "unavailable")],
)
def test_provider_errors_are_safe_and_not_retried(fake_voyage, status, message):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"detail": "test-secret-key private text"})

    fake_voyage(handler)
    with pytest.raises(EmbeddingError, match=message) as error:
        embed_documents(["Text."], settings())
    assert len(calls) == 1
    assert "test-secret-key" not in str(error.value)
    assert "private text" not in str(error.value)


@pytest.mark.parametrize(
    "exception,message", [(httpx.ReadTimeout, "timed out"), (httpx.ConnectError, "connect")]
)
def test_network_errors(fake_voyage, exception, message):
    def handler(request):
        raise exception("Private error details.", request=request)

    fake_voyage(handler)
    with pytest.raises(EmbeddingError, match=message):
        embed_documents(["Text."], settings())


@pytest.mark.parametrize("kind", ["dimensions", "nan", "missing_usage", "duplicate_indices", "missing_vector"])
def test_rejects_inconsistent_provider_responses(fake_voyage, kind):
    response = payload(2)
    if kind == "dimensions":
        response["data"][0]["embedding"] = [0.1, 0.2]
    elif kind == "nan":
        response["data"][0]["embedding"][0] = float("nan")
    elif kind == "missing_usage":
        del response["usage"]
    elif kind == "duplicate_indices":
        response["data"][1]["index"] = 0
    elif kind == "missing_vector":
        response["data"].pop()

    fake_voyage(lambda request: httpx.Response(200, content=json.dumps(response)))
    with pytest.raises(EmbeddingError):
        embed_documents(["First.", "Second."], settings())


def test_rejects_invalid_json(fake_voyage):
    fake_voyage(lambda request: httpx.Response(200, text="Not JSON."))
    with pytest.raises(EmbeddingError, match="invalid embedding response"):
        embed_documents(["Text."], settings())


def test_stops_after_failed_batch(fake_voyage):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload()) if len(calls) == 1 else httpx.Response(429)

    fake_voyage(handler)
    with pytest.raises(EmbeddingError, match="rate limit"):
        embed_documents(["First.", "Second.", "Third."], settings(voyage_batch_size=1))
    assert len(calls) == 2
