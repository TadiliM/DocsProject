from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from psycopg import Error as DatabaseError

from app.chunking import chunk_pages
from app.config import Settings, get_settings
from app.database import check_database
from app.pdf import InvalidPDFError, PDFPageLimitError, extract_pdf_pages
from app.schemas import DocumentExtractionResponse, HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup if environment settings are invalid.
    get_settings()
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


@app.post("/documents", response_model=DocumentExtractionResponse)
def extract_document(
    file: UploadFile,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentExtractionResponse:
    """Extract PDF pages and chunks for inspection. Documents are not stored yet."""
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
    return DocumentExtractionResponse(
        filename=filename,
        page_count=len(pages),
        pages=pages,
        chunk_count=len(chunks),
        chunks=chunks,
    )
