# DocsProject — AI Document Search

A learning project: build an application that answers questions about PDF documents
and displays the source passages. The priority is understanding the Python backend.

## Design decisions

- A public library: all visitors will query the same documents.
- Document uploads and deletions will be restricted to the administrator before deployment.
- Text-based PDFs only, without OCR or encrypted documents.
- Each question will target one selected document, without conversation memory.
- FastAPI and Pydantic, served by Uvicorn.
- PostgreSQL and pgvector for storage and future vector search.
- External APIs for embeddings and generation. No models run locally.
- Eventually: a simple React frontend and deployment to a VPS.

## Current status: steps 1–7

Implemented: health endpoint, environment configuration, PDF upload validation,
text extraction page by page, chunking with configurable overlap, a PostgreSQL
schema with pgvector, and Python functions to save and read documents and chunks.

`POST /documents` currently returns extracted pages and chunks for inspection. It does not
save files, create database records, calculate embeddings, or generate answers.
The repository functions are ready, but will be connected to the upload pipeline
in step 9 after the embedding API is added.
The upload route is currently unprotected and is intended for local development.

## Run the backend

Requires Python 3.10 or newer. From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cp .env.example .env
docker compose up -d --wait db
python -m uvicorn app.main:app --app-dir backend --reload
```

If `python3` is too old, use a newer executable, for example
`python3.12 -m venv .venv`. If `.env` already exists, edit it instead of copying
over it. The existing local `.venv` was created with Python 3.12.

- Health check: http://127.0.0.1:8000/health
- Database readiness: http://127.0.0.1:8000/health/db
- Interactive API documentation: http://127.0.0.1:8000/docs

Uvicorn receives HTTP requests and calls `app` in the `app.main` module. FastAPI
selects the route; Pydantic defines and validates data structures.
`--reload` is for development only.

## Configuration

Settings are read from the project-root `.env` file and environment variables.
Environment variables take precedence. Defaults apply when values are absent.
Invalid values cause startup to fail. Restart the server after editing `.env`.

| Variable | Default | Allowed values | Purpose |
|---|---|---|---|
| `MAX_UPLOAD_MB` | `10` | 1–50 | Maximum PDF size in MiB (1 MiB = 1,048,576 bytes) |
| `MAX_PDF_PAGES` | `100` | 1–500 | Maximum number of pages per document |
| `CHUNK_SIZE` | `1000` | 1–10000 | Maximum characters per chunk |
| `CHUNK_OVERLAP` | `200` | 0 to `CHUNK_SIZE - 1` | Shared characters between consecutive windows on a page |
| `POSTGRES_HOST` | `127.0.0.1` | Hostname or IP address | Database host for the backend |
| `POSTGRES_PORT` | `5433` | 1–65535 | Database port on the host |
| `POSTGRES_DB` | `docsproject` | Database name | Database used by the backend and Compose |
| `POSTGRES_USER` | `docsproject` | PostgreSQL role | Local database user |
| `POSTGRES_PASSWORD` | `docsproject_local_only` | Password | Development-only credential; change before deployment |

`CHUNK_OVERLAP` must be smaller than `CHUNK_SIZE`. Existing `.env` files can omit
these new variables to use the defaults.

`.env` is ignored by Git. `.env.example` contains non-secret example values.
No API keys are required for this stage. Model provider configuration will be
added when external APIs are integrated.

## Upload and extract a PDF

In `/docs`, expand `POST /documents`, select **Try it out**, choose a PDF, and
select **Execute**. Alternatively:

```bash
curl -X POST http://127.0.0.1:8000/documents \
  -F 'file=@/absolute/path/to/document.pdf'
```

Example response (`200 OK`):

```json
{
  "filename": "document.pdf",
  "page_count": 2,
  "pages": [
    {"page_number": 1, "text": "The internship lasts six months."},
    {"page_number": 2, "text": "Applications close in January."}
  ],
  "chunk_count": 2,
  "chunks": [
    {"chunk_index": 0, "page_number": 1, "text": "The internship lasts six months."},
    {"chunk_index": 1, "page_number": 2, "text": "Applications close in January."}
  ]
}
```

Page numbers start at 1. Blank pages are preserved with an empty `text` value.
A document is rejected if none of its pages contain extractable text. Scanned
pages within a mixed document may remain empty because no OCR is performed.
Tables and complex layouts may produce imperfect text extraction.

## Chunking

Each page is split independently into windows of at most `CHUNK_SIZE` characters.
The next window starts `CHUNK_SIZE - CHUNK_OVERLAP` characters after the previous
one. For a size of 10 and an overlap of 3:

```text
Page:     abcdefghijklmnopq
Chunk 0:  abcdefghij
Chunk 1:         hijklmnopq
```

Chunks never cross page boundaries, so every chunk has a single source page.
`chunk_index` starts at 0 and increases across the whole document. Page numbers
start at 1. Blank pages produce no chunks. Leading and trailing whitespace is
removed from pages and chunks; whitespace-only windows are skipped. As a result,
the shared text in returned chunks may be shorter than the configured overlap.

This deliberately simple algorithm counts Python characters, not tokens, and can
split words or sentences. Provider-specific token limits will be checked when
embedding APIs are integrated. No additional dependencies are needed for chunking.

## PostgreSQL and pgvector

Requires Docker with Compose. Start Docker Desktop on macOS before running:

```bash
docker compose up -d --wait db
docker compose ps
```

Compose reads the project-root `.env`. Existing `.env` files must include the
`POSTGRES_*` entries from `.env.example`; do not overwrite existing settings.
The database listens on `127.0.0.1:5433` by default. Port 5433 avoids conflicting
with a separate PostgreSQL installation on the usual port 5432. Inside the
container, PostgreSQL still listens on 5432. The backend currently runs on the host.

`compose.yaml` uses PostgreSQL 17 with pgvector 0.8.7. On the first start with an
empty volume, PostgreSQL runs `backend/sql/001_init.sql`. It creates the vector
extension and two tables:

| Table | Main columns | Purpose |
|---|---|---|
| `documents` | `id`, `filename`, `page_count`, `created_at` | Document metadata |
| `chunks` | `id`, `document_id`, `chunk_index`, `page_number`, `text`, `embedding` | Text passages and future embeddings |

Each chunk belongs to a document. The database prevents duplicate chunk indices
within a document and automatically removes its chunks when the document is
deleted. The unique `(document_id, chunk_index)` index also supports lookups by
document. No vector search index is needed at this stage.

`embedding` is a nullable `vector` column without a fixed dimension for now.
Step 8 will select the model and fix its dimensions before embeddings are stored
by the application. The current repository leaves this column empty.

Data is stored in the named Docker volume `postgres_data` and survives container
restarts. To stop the project's database without removing its data:

```bash
docker compose stop db
```

Initialization scripts only run automatically on a fresh database. Editing the
SQL file does not update an existing schema, and `CREATE TABLE IF NOT EXISTS`
does not migrate existing tables. Future schema changes will need explicit SQL
migrations. Database credentials are also established at first initialization;
editing `.env` alone does not change an existing PostgreSQL role's password.

## Python database access

`database.py` opens synchronous Psycopg connections with parameterized connection
arguments, dictionary results, a 3-second connection timeout, and a 5-second SQL
statement timeout. The password is held in a Pydantic `SecretStr` so it is masked
in the settings representation.

Use a connection in a `with` block. Psycopg commits on success, rolls back on an
exception, and closes the connection when the block ends. `repository.py` provides:

- `create_document(connection, filename, page_count, chunks)` to save metadata
  and chunks together in a transaction. A failed chunk insert rolls back the
  document insert as well. With an already active transaction, it uses a savepoint;
  the outer transaction still controls the final commit.
- `get_document(connection, document_id)` to read metadata or return `None`.
- `get_document_chunks(connection, document_id)` to read passages in index order.

All SQL values are passed as parameters, including filenames and document IDs.
Connections are opened only when needed; no pool or ORM is used in this MVP.

`GET /health/db` checks connectivity, the pgvector extension, and the presence of
the public `documents` and `chunks` tables. It returns `200` with `{"status":"ok"}`
when ready, or `503` with a generic error if the database is unavailable or not
initialized. Credentials and database errors are not returned to visitors.
`GET /health` and PDF extraction still work while PostgreSQL is stopped.

The filename must end with `.pdf` (case-insensitive). The backend also checks
the PDF header and parses the content; it does not trust the MIME type alone.

| Status | Meaning |
|---|---|
| `400` | Empty uploaded file |
| `413` | File size or page limit exceeded |
| `415` | Unsupported filename extension |
| `422` | Missing file, invalid PDF, encrypted PDF, or no extractable text |

Errors use FastAPI's `detail` field. These limits bound file reading and processing
in the endpoint. Multipart uploads are parsed before the endpoint runs; a request
body limit at the reverse proxy will also be needed before public deployment.
PDF size and page limits do not guarantee a fixed extraction time or memory use.

`GET /health` returns `{"status": "ok"}`. It only checks that the API responds,
not database or model provider availability.

## Project structure

```text
.env.example
compose.yaml
pytest.ini
backend/
├── app/
│   ├── __init__.py
│   ├── config.py        # Environment settings and validation
│   ├── chunking.py      # Character-based chunking with overlap
│   ├── database.py      # Psycopg connections and readiness check
│   ├── main.py          # Application and HTTP endpoints
│   ├── pdf.py           # PDF parsing and text extraction
│   ├── repository.py    # Parameterized SQL for documents and chunks
│   └── schemas.py       # API response models
├── sql/
│   └── 001_init.sql     # Extension, tables, and constraints
├── tests/
│   ├── conftest.py      # Test client and generated PDF fixtures
│   ├── test_config.py
│   ├── test_chunking.py
│   ├── test_database.py
│   └── test_documents.py
├── requirements.txt
└── requirements-dev.txt
```

Request flow: `main.py` checks the upload, `pdf.py` extracts the pages,
`chunking.py` creates the chunks, and `schemas.py` defines the JSON response.
`config.py` supplies the limits and chunking parameters.
The extraction function is synchronous; the endpoint uses `def` so FastAPI runs
it in a thread pool rather than directly blocking the async event loop.

## Run tests

From the project root, with the virtual environment activated:

```bash
python -m pip install -r backend/requirements-dev.txt
python -m pytest -q
```

Tests generate small real PDFs in memory. They cover extraction, page numbering,
blank pages, invalid and encrypted files, upload limits, missing files, and
configuration loading and validation. Chunking tests cover overlap, text coverage,
page boundaries, empty pages, Unicode text, and the configured upload response.
No external APIs are required. The default test run skips the six database
integration tests. To run the full suite with the project's PostgreSQL running:

```bash
docker compose up -d --wait db
python -m pytest -q --run-db-tests
```

Integration tests create and remove isolated temporary schemas in the configured
local database. They do not modify the public library. They verify committed
writes across connections, reads, rollback on failure, cascade deletion, table
constraints, and a synthetic vector round trip. Database readiness error responses
are also tested without requiring PostgreSQL.

## Next steps

1. Request embeddings from an external API (step 8).
2. Connect the upload pipeline to embeddings and storage (step 9).
3. Retrieve relevant passages for a question.
4. Generate an answer with sources.
5. Add administrator protection, public usage limits, the frontend, and VPS deployment.
