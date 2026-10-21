from typing import Literal

import httpx
from pydantic import BaseModel, Field, FiniteFloat

from app.config import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, Settings


VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


class EmbeddingError(RuntimeError):
    """An embedding request could not be completed safely."""


class EmbeddingResult(BaseModel):
    model: str = EMBEDDING_MODEL
    dimensions: int = EMBEDDING_DIMENSIONS
    embeddings: list[list[float]]
    total_tokens: int


class _EmbeddingItem(BaseModel):
    index: int = Field(ge=0, strict=True)
    embedding: list[FiniteFloat] = Field(
        min_length=EMBEDDING_DIMENSIONS, max_length=EMBEDDING_DIMENSIONS
    )


class _Usage(BaseModel):
    total_tokens: int = Field(ge=0, strict=True)


class _VoyageResponse(BaseModel):
    data: list[_EmbeddingItem]
    usage: _Usage


def embed_documents(texts: list[str], settings: Settings) -> EmbeddingResult:
    """Embed passages in batches, preserving the input order."""
    return _embed_texts(texts, "document", settings)


def embed_query(question: str, settings: Settings) -> EmbeddingResult:
    """Embed a question using the same model and dimensions as document passages."""
    return _embed_texts([question], "query", settings)


def _embed_texts(
    texts: list[str], input_type: Literal["document", "query"], settings: Settings
) -> EmbeddingResult:
    if not texts:
        return EmbeddingResult(embeddings=[], total_tokens=0)
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("Embedding inputs must be non-empty text strings.")

    api_key = settings.voyage_api_key.get_secret_value().strip()
    if not api_key:
        raise EmbeddingError("Set VOYAGE_API_KEY in .env before requesting embeddings.")

    embeddings = []
    total_tokens = 0
    with httpx.Client(timeout=settings.voyage_timeout_seconds) as client:
        for start in range(0, len(texts), settings.voyage_batch_size):
            batch = texts[start : start + settings.voyage_batch_size]
            try:
                response = client.post(
                    VOYAGE_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "input": batch,
                        "model": EMBEDDING_MODEL,
                        "input_type": input_type,
                        "output_dimension": EMBEDDING_DIMENSIONS,
                        "output_dtype": "float",
                        "truncation": False,
                    },
                )
            except httpx.TimeoutException:
                raise EmbeddingError("The Voyage embedding request timed out.") from None
            except httpx.RequestError:
                raise EmbeddingError("Could not connect to the Voyage API.") from None

            if response.status_code in (401, 403):
                raise EmbeddingError("Voyage authentication failed. Check VOYAGE_API_KEY.")
            if response.status_code == 429:
                raise EmbeddingError(
                    "Voyage rate limit or usage quota reached. Check your account and try later."
                )
            if response.status_code in (400, 422):
                raise EmbeddingError(
                    "Voyage rejected the request. Check input length and model parameters."
                )
            if not response.is_success:
                raise EmbeddingError("The Voyage embedding service is unavailable.")

            try:
                result = _VoyageResponse.model_validate(response.json())
            except ValueError:
                raise EmbeddingError("Voyage returned an invalid embedding response.") from None

            ordered = sorted(result.data, key=lambda item: item.index)
            if [item.index for item in ordered] != list(range(len(batch))):
                raise EmbeddingError("Voyage returned inconsistent embedding indices.")
            embeddings.extend(item.embedding for item in ordered)
            total_tokens += result.usage.total_tokens

    return EmbeddingResult(embeddings=embeddings, total_tokens=total_tokens)


def main() -> None:
    """Run an explicit, small live request without printing the key or vectors."""
    from app.config import get_settings

    try:
        result = embed_documents(["The internship lasts six months."], get_settings())
    except EmbeddingError as error:
        raise SystemExit(str(error)) from None
    print(
        f"Model: {result.model}; vectors: {len(result.embeddings)}; "
        f"dimensions: {result.dimensions}; tokens: {result.total_tokens}"
    )


if __name__ == "__main__":
    main()
