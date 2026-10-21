from datetime import datetime

from pydantic import BaseModel


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
