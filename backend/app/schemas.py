from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    status: str


class PageText(BaseModel):
    page_number: int
    text: str


class DocumentChunk(BaseModel):
    chunk_index: int
    page_number: int
    text: str


class StoredDocument(BaseModel):
    id: int
    filename: str
    page_count: int
    created_at: datetime


class StoredChunk(DocumentChunk):
    id: int
    document_id: int


class DocumentExtractionResponse(BaseModel):
    filename: str
    page_count: int
    pages: list[PageText]
    chunk_count: int
    chunks: list[DocumentChunk]


class DocumentUploadResponse(DocumentExtractionResponse):
    id: int
    created_at: datetime
    embedding_model: str
    embedding_tokens: int


class DocumentSummary(StoredDocument):
    chunk_count: int


class SearchRequest(BaseModel):
    document_id: int = Field(gt=0)
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("The question must not be blank.")
        return value


class SearchMatch(DocumentChunk):
    chunk_id: int
    similarity: float


class SearchResponse(BaseModel):
    document_id: int
    filename: str
    question: str
    matches: list[SearchMatch]
    embedding_tokens: int


class QuestionRequest(SearchRequest):
    """Use the same document, question, and retrieval limits as search."""


class AnswerSource(SearchMatch):
    source_id: int
    document_id: int
    filename: str


class GenerationUsage(BaseModel):
    prompt_tokens: int = Field(ge=0, strict=True)
    completion_tokens: int = Field(ge=0, strict=True)
    total_tokens: int = Field(ge=0, strict=True)


class QuestionResponse(BaseModel):
    document_id: int
    filename: str
    question: str
    answer: str
    answerable: bool
    sources: list[AnswerSource]
    embedding_tokens: int
    llm_model: str | None
    llm_usage: GenerationUsage | None
