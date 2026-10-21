from contextlib import asynccontextmanager
import logging
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Response, UploadFile
from psycopg import Error as DatabaseError

from app.auth import require_admin_key
from app.chunking import chunk_pages
from app.config import Settings, get_settings
from app.database import check_database, get_connection
from app.embeddings import EmbeddingError, embed_documents
from app.generation import GenerationConfigurationError, GenerationError
from app.pdf import InvalidPDFError, PDFPageLimitError, extract_pdf_pages
from app.repository import create_document, delete_document, list_documents
from app.questions import answer_question
from app.rate_limit import SlidingWindowLimiter, enforce_rate_limit
from app.retrieval import DocumentNotFoundError, retrieve_passages
from app.schemas import (
    DocumentSummary, DocumentUploadResponse, HealthResponse, QuestionRequest,
    QuestionResponse, SearchRequest, SearchResponse,
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup if environment settings are invalid.
    get_settings()
    app.state.rate_limiter = SlidingWindowLimiter()
    yield


app = FastAPI(
    title="DocsProject API",
    description="Search API for a public PDF library.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Check that the API is responding."""
    return HealthResponse(status="ok")


@app.get(
    "/health/db",
    response_model=HealthResponse,
    responses={503: {"description": "Database is unavailable or not initialized."}},
)
def database_health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Check PostgreSQL connectivity and schema readiness."""
    try:
        ready = check_database(settings)
    except DatabaseError:
        ready = False
    if not ready:
        raise HTTPException(status_code=503, detail="Database is unavailable or not initialized.")
    return HealthResponse(status="ok")


@app.post(
    "/documents", response_model=DocumentUploadResponse, status_code=201,
    dependencies=[Depends(require_admin_key)],
    responses={
        401: {"description": "Invalid or missing administrator key."},
        503: {"description": "Administrator access or database unavailable."},
    },
)
def upload_document(
    file: UploadFile,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentUploadResponse:
    """Extract, embed, and save a text-based PDF to the public library."""
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Only PDF files are supported.")

    # Read at most the allowed size plus one byte to detect oversized files.
    content = file.file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"PDFs must not exceed {settings.max_upload_mb} MiB.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    try:
        pages = extract_pdf_pages(content, max_pages=settings.max_pdf_pages)
    except PDFPageLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except InvalidPDFError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    chunks = chunk_pages(pages, settings.chunk_size, settings.chunk_overlap)
    try:
        # Avoid spending tokens when the database is already unavailable.
        # This check closes its connection before calling Voyage.
        if not check_database(settings):
            raise HTTPException(status_code=503, detail="Database is unavailable or not initialized.")
        result = embed_documents([chunk.text for chunk in chunks], settings)
        # No database transaction is held open during the external API calls.
        with get_connection(settings) as connection:
            document = create_document(
                connection, filename, len(pages), chunks, result.embeddings
            )
    except EmbeddingError:
        raise HTTPException(
            status_code=502,
            detail="Document indexing failed. Check the Voyage configuration or try again later.",
        ) from None
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database operation failed. Try again later.") from None

    return DocumentUploadResponse(
        id=document.id,
        created_at=document.created_at,
        filename=filename,
        page_count=len(pages),
        pages=pages,
        chunk_count=len(chunks),
        chunks=chunks,
        embedding_model=result.model,
        embedding_tokens=result.total_tokens,
    )


@app.get("/documents", response_model=list[DocumentSummary])
def document_library(
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentSummary]:
    """List the shared library, newest documents first."""
    try:
        with get_connection(settings) as connection:
            return list_documents(connection, limit, offset)
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database operation failed. Try again later.") from None


@app.delete(
    "/documents/{document_id}", status_code=204, response_class=Response,
    dependencies=[Depends(require_admin_key)],
    responses={
        401: {"description": "Invalid or missing administrator key."},
        503: {"description": "Administrator access or database unavailable."},
    },
)
def remove_document(
    document_id: Annotated[int, Path(gt=0)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Delete a document and all its chunks from the public library."""
    try:
        with get_connection(settings) as connection:
            deleted = delete_document(connection, document_id)
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database operation failed. Try again later.") from None
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found.")
    return Response(status_code=204)


@app.post(
    "/search", response_model=SearchResponse,
    dependencies=[Depends(enforce_rate_limit)],
    responses={429: {"description": "Shared search/question rate limit exceeded."}},
)
def search_document(
    request: SearchRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchResponse:
    """Retrieve source passages for a question about one selected document."""
    try:
        return retrieve_passages(request, settings)
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.") from None
    except (EmbeddingError, ValueError):
        raise HTTPException(
            status_code=502,
            detail="Question embedding failed. Check the Voyage configuration or try again later.",
        ) from None
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database operation failed. Try again later.") from None


@app.post(
    "/questions", response_model=QuestionResponse,
    dependencies=[Depends(enforce_rate_limit)],
    responses={429: {"description": "Shared search/question rate limit exceeded."}},
)
def ask_question(
    request: QuestionRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> QuestionResponse:
    """Answer a question from one document and return verified source metadata."""
    try:
        return answer_question(request, settings)
    except GenerationConfigurationError:
        raise HTTPException(status_code=503, detail="Set GROQ_API_KEY on the server before asking questions.") from None
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.") from None
    except (EmbeddingError, ValueError):
        raise HTTPException(status_code=502, detail="Question embedding failed. Try again later.") from None
    except GenerationError as error:
        # GenerationError messages are controlled locally; never log provider bodies.
        logger.warning("Answer generation failed: %s", error)
        raise HTTPException(status_code=502, detail="Answer generation failed. Check the Groq configuration or try again later.") from None
    except DatabaseError:
        raise HTTPException(status_code=503, detail="Database operation failed. Try again later.") from None
