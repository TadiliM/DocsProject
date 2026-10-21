# DocsProject — AI Document Search

A learning project: build an application that answers questions about PDF documents
and displays the source passages. The priority is understanding the Python backend.

## Design decisions

- A public library: all visitors will query the same documents.
- Document uploads and deletions require a private administrator key.
- Text-based PDFs only, without OCR or encrypted documents.
- Each question will target one selected document, without conversation memory.
- FastAPI and Pydantic, served by Uvicorn.
- PostgreSQL and pgvector for storage and vector search.
- Voyage API for embeddings; Qwen 3.8 27B via Groq for answer generation.
  No models run locally.
- A simple React frontend, with production files prepared for the existing VPS/Caddy setup.

## Current status

The backend and simple English React frontend are implemented. Docker images and
Caddy deployment files are prepared for **docsproject.mtadili.dev**. Remote
deployment and manual site validation are still to be performed by the project
owner. No frontend tests were added or run.

- [VPS deployment instructions](deploy/DEPLOYMENT.md)
- [Manual site checks for the project owner](docs/MANUAL_CHECKS.md)
- [VPS versus AWS and billing considerations](docs/HOSTING.md)

### Backend: steps 1–15

Implemented: health endpoint, environment configuration, PDF upload validation,
text extraction page by page, chunking with configurable overlap, a PostgreSQL
schema with pgvector, Python functions to save and read documents and chunks,
and a Voyage embedding client for passages and questions. Uploads now persist
metadata, chunks, and vectors. The shared library can be listed and documents deleted.
Questions can now retrieve ranked passages from one selected document.
The question endpoint generates answers with citations and source passages.
Search and questions share a basic per-IP rate limit.

`POST /documents` requires PostgreSQL and a valid Voyage API key. It returns the
saved document ID, extracted pages and chunks, and embedding usage. Original PDF
files are not retained; text and vectors are stored in PostgreSQL.
`POST /search` returns passages without generating an answer. `POST /questions`
adds Groq answer generation, citation validation, and source metadata.

Upload and deletion require the `X-Admin-Key` header. Listing documents, searching,
and asking questions remain public. The public frontend does not contain the
administrator key or offer document uploads.

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

## Run the React frontend locally

Use Node 22.12 or newer. Keep the backend running on port 8000, then in a separate
terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open the URL printed by Vite (normally http://127.0.0.1:5173). The development proxy
forwards `/api/*` to FastAPI. Both development and production use relative `/api`
URLs, so no CORS configuration or frontend environment file is required.

The frontend uses React, Vite, plain JavaScript, and one CSS file. It provides a
document selector, question form, loading/error/empty states, an answer, clickable
citations, and source passages. It displays the first 100 documents, which is
sufficient for the small fixed demonstration library. There is no public upload,
account system, router, component library, or browser-side API key.

```bash
npm run build
```

This creates `frontend/dist`. No frontend tests were written or run. The build and
both Docker image builds succeeded locally; browser and live Qwen validation are
left to the project owner as requested.

For deployment, follow [deploy/DEPLOYMENT.md](deploy/DEPLOYMENT.md). The separate
`compose.production.yaml` starts the API, static frontend, and private database;
your existing Caddy container remains responsible for HTTPS and routing. Do not
merge it with the local `compose.yaml`, which exposes a development database port.
Backups, environment creation, Caddy setup, updates, and manual checks are covered
in the deployment guide. No remote deployment or Git push was performed.

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
| `VOYAGE_API_KEY` | Empty | Secret API key | Required only when requesting embeddings |
| `VOYAGE_TIMEOUT_SECONDS` | `30` | Greater than 0, at most 120 | HTTP timeout in seconds |
| `VOYAGE_BATCH_SIZE` | `16` | 1–16 | Maximum passages per embedding request |
| `GROQ_API_KEY` | Empty | Secret API key | Required for `POST /questions` |
| `GROQ_TIMEOUT_SECONDS` | `30` | Greater than 0, at most 120 | Generation HTTP timeout in seconds |
| `LLM_MAX_COMPLETION_TOKENS` | `512` | 64–2048 | Maximum generated tokens per answer |
| `LLM_MAX_CONTEXT_CHARS` | `6000` | 500–12000 | Total source text characters sent to Groq |
| `RATE_LIMIT_REQUESTS` | `3` | 1–100 | Shared search/question requests allowed per IP per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | 1–3600 | Sliding rate limit window in seconds |
| `ADMIN_API_KEY` | Empty | Private random key | Required to upload or delete documents; empty disables those operations |

`CHUNK_OVERLAP` must be smaller than `CHUNK_SIZE`. Existing `.env` files can omit
these new variables to use the defaults.

`.env` is ignored by Git. `.env.example` contains non-secret example values.
Uploading and indexing a PDF requires a Voyage key. Health checks, library listing,
and deletion do not call Voyage. Add a key only to the local `.env` or server
environment, never to source files.

## Administrator access

This MVP uses one administrator key instead of accounts, passwords, or JWTs.
`auth.py` compares the private server value with the `X-Admin-Key` request header.
The comparison uses `secrets.compare_digest`. The key is stored as a Pydantic
`SecretStr`, not in source code or the public frontend.

The current local `.env` contains a generated random administrator key. Open the
file locally to access it. On a fresh installation, generate a random key with:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Set that value as `ADMIN_API_KEY` in `.env`, then restart the backend. An empty
server key disables uploads and deletions with `503`; a missing or incorrect
request key returns `401`. Authentication is enforced before PDF extraction,
model calls, or database mutations. Multipart parsing can still happen before
the dependency runs, so a reverse-proxy body size limit remains part of deployment.

For local administration through Swagger UI:

1. Open http://127.0.0.1:8000/docs.
2. Select **Authorize** and enter the `ADMIN_API_KEY` value under **AdminKey**.
3. Upload or delete documents using the corresponding routes.

Only `POST /documents` and `DELETE /documents/{document_id}` require this key.
`GET /documents`, `/search`, `/questions`, and health routes do not. Knowing a
document ID does not grant permission to modify the library. Query parameters
cannot replace the authentication header.

Keep the key on the server and in your private administration client. Do not
include it in the public frontend build. Use HTTPS when administering the deployed
site. To rotate the key, change `.env` and restart the backend; PostgreSQL is not
involved. Losing the key does not require changing or deleting document data.

## Upload and index a PDF

Start PostgreSQL and set `VOYAGE_API_KEY` in `.env` before uploading.

In `/docs`, expand `POST /documents`, select **Try it out**, choose a PDF, and
select **Execute** after authorizing as described above. Alternatively, replace
the placeholder header value with your private key:

```bash
curl -X POST http://127.0.0.1:8000/documents \
  -H 'X-Admin-Key: YOUR_ADMIN_KEY' \
  -F 'file=@/absolute/path/to/document.pdf'
```

Example response (`201 Created`; IDs, dates, and token usage vary):

```json
{
  "id": 1,
  "created_at": "2026-10-21T10:00:00Z",
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
  ],
  "embedding_model": "voyage-4-lite",
  "embedding_tokens": 15
}
```

Page numbers start at 1. Blank pages are preserved with an empty `text` value.
A document is rejected if none of its pages contain extractable text. Scanned
pages within a mixed document may remain empty because no OCR is performed.
Tables and complex layouts may produce imperfect text extraction.

The pipeline is synchronous:

```text
Upload -> PDF validation -> Text extraction -> Chunking
       -> Database readiness check -> Voyage embeddings
       -> Transaction: document + chunks + vectors -> 201 Created
```

The database is checked before calling Voyage to avoid spending tokens when it
is already unavailable. This connection is closed before the external calls.
Only after all embedding batches succeed is the write transaction opened. If a
chunk or vector insert fails, the document and all its chunks are rolled back.
An API failure leaves no partially indexed document in the library.

Earlier successful Voyage batches can still consume tokens if a later batch or
database write fails. Re-uploading creates a new document ID, even when the
filename is identical. No automatic deduplication or retries are implemented.
Full vectors are not included in the upload response.

## List and delete documents

`GET /documents` returns shared document metadata, newest first, including the
number of chunks. It returns an empty list when the library is empty. It does not
return extracted text or vectors and does not call Voyage.

```bash
curl 'http://127.0.0.1:8000/documents?limit=20&offset=0'
```

`limit` defaults to 100 and accepts 1–100; `offset` defaults to 0 and must be
non-negative. All visitors will see the same library.

```json
[
  {
    "id": 1,
    "filename": "document.pdf",
    "page_count": 2,
    "created_at": "2026-10-21T10:00:00Z",
    "chunk_count": 2
  }
]
```

`DELETE /documents/{document_id}` removes the metadata and automatically cascades
to the document's chunks and vectors. It returns `204 No Content` when deleted,
`404` if the document does not exist, and `422` for an invalid ID. This changes
the shared library for every visitor.

```bash
curl -i -X DELETE http://127.0.0.1:8000/documents/1 \
  -H 'X-Admin-Key: YOUR_ADMIN_KEY'
```

## Search for passages

`POST /search` accepts a document ID, question, and optional `top_k` (default 3,
allowed range 1–10). The question must contain 1–2000 characters and cannot be
whitespace-only. Leading and trailing whitespace is removed.

Upload a PDF, take its returned ID, then try this in `/docs` or with curl:

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"document_id": 1, "question": "How long is the internship?", "top_k": 3}'
```

Example response (`200 OK`; IDs, scores, and usage vary):

```json
{
  "document_id": 1,
  "filename": "document.pdf",
  "question": "How long is the internship?",
  "embedding_tokens": 7,
  "matches": [
    {
      "chunk_id": 1,
      "chunk_index": 0,
      "page_number": 1,
      "text": "The internship lasts six months.",
      "similarity": 0.75
    }
  ]
}
```

The backend first checks that the document exists. A missing document returns
`404` without spending Voyage tokens. It then closes the connection, embeds the
question using `input_type="query"`, and opens a new connection to retrieve the
closest passages. A second existence check handles deletion during the API call.
No database transaction is kept open while waiting for Voyage.

`repository.py` uses pgvector's cosine distance operator `<=>` and returns
`similarity = 1 - distance`. Higher scores mean closer vectors. Cosine similarity
ranges from -1 to 1; it is not a probability or a confidence percentage. The
search uses exact nearest neighbors without an approximate vector index.
See the [pgvector documentation](https://github.com/pgvector/pgvector#querying).

SQL always filters by the selected `document_id`, orders by distance (then chunk
index for ties), and limits the results to `top_k`. Passages from other documents
cannot appear. Null and zero stored vectors are skipped, since they are not
usable for cosine search. The query must be a finite, nonzero 1024-dimensional
vector. An existing document without searchable vectors returns an empty list.

There is no relevance threshold yet: the closest passages are returned even if
the document does not answer the question. This endpoint does not generate an
answer, maintain conversation history, or send passages to a generation model.
It exposes retrieval results separately so they can be checked independently of the LLM.

Search errors: `422` for invalid request data, `404` for a missing document,
`502` for a question embedding failure, and `503` for a database failure. Raw
provider and database errors are not returned. The only model call is to Voyage.

## Ask a question with sources

1. Create an API key in the [Groq console](https://console.groq.com/keys).
2. Set `GROQ_API_KEY` in your local `.env` without sharing or committing it.
3. Restart the backend to reload settings.
4. Upload a PDF and use its returned ID with `POST /questions`.

The generation model is fixed to `qwen/qwen3.8-27b` in `config.py`. The client calls
Groq's chat completions endpoint directly through HTTPX. No SDK, local model, or
new database migration is needed. Qwen's reasoning mode is disabled for concise
answers. The request uses strict JSON-schema output, followed by local validation.
See [Groq structured outputs](https://console.groq.com/docs/structured-outputs)
and [reasoning controls](https://console.groq.com/docs/reasoning).

```bash
curl -X POST http://127.0.0.1:8000/questions \
  -H 'Content-Type: application/json' \
  -d '{"document_id": 1, "question": "How long is the internship?", "top_k": 3}'
```

The request inherits the same fields and limits as `/search`. Example response
(`200 OK`; IDs, scores, and usage vary):

```json
{
  "document_id": 1,
  "filename": "document.pdf",
  "question": "How long is the internship?",
  "answer": "The internship lasts six months. [1]",
  "answerable": true,
  "sources": [
    {
      "source_id": 1,
      "document_id": 1,
      "filename": "document.pdf",
      "chunk_id": 1,
      "chunk_index": 0,
      "page_number": 1,
      "text": "The internship lasts six months.",
      "similarity": 0.75
    }
  ],
  "embedding_tokens": 7,
  "llm_model": "qwen/qwen3.8-27b",
  "llm_usage": {
    "prompt_tokens": 300,
    "completion_tokens": 30,
    "total_tokens": 330
  }
}
```

The pipeline reuses retrieval, then sends only the question and selected passages
to Groq. There is no conversation history. The prompt asks for an answer in the
question's language using only those passages, and treats document text as data
rather than instructions. No database connection remains open during generation.
The Groq key is checked before retrieval to avoid spending Voyage tokens when
generation is not configured. Missing document checks still avoid model calls
once the generation key is configured.

`LLM_MAX_CONTEXT_CHARS` limits total passage text, not tokens or the complete HTTP
request. The last passage may be truncated to fit the budget; returned source text
is exactly the passage text sent to Groq. Lower this limit and output tokens if
your account's token rate limit is restrictive. Provider limits still apply.

Groq returns `answer`, `answerable`, and numeric `source_ids`. The backend checks:

- The completion finished normally rather than being cut off or refused.
- The answer matches the expected JSON structure and is not blank.
- Every citation ID corresponds to a passage actually sent to the model.
- Inline citations such as `[1]` match the distinct IDs in `source_ids`.
- An answer marked answerable has at least one citation.

The model never supplies filenames or page numbers. `questions.py` resolves each
source ID to retrieved database metadata and returns only the cited sources.
IDs are preserved when filtering: an answer citing `[2]` returns `source_id: 2`.
Invalid citations produce `502`, rather than being displayed as valid sources.

If retrieval produces no usable passages, Groq is skipped. If Qwen reports that
the evidence is insufficient, the backend uses the same standard response:

```text
The provided passages do not contain enough information to answer this question.
```

Both cases return `answerable: false` and `sources: []`. The fallback text is in
English. Without a Groq call, `llm_model` and `llm_usage` are null; when Qwen
abstains, its token usage is still returned. This is not a calibrated confidence
score. Citation validation verifies references, not whether every statement is
entailed by the text; prompt instructions and structured output do not eliminate
hallucinations or prompt injection.

Errors use `404` for a missing document, `422` for invalid input, `503` for missing
Groq configuration or database failure, and `502` for embedding or generation
failure. Authentication errors, rate limits, timeouts, malformed output, and
truncated completions are handled without returning raw provider details. There
are no automatic retries or account-wide usage limits yet.

`/documents` and `/search` continue to work without a Groq key. Normal tests
simulate both providers; an actual Qwen request requires a configured key.

## Basic per-IP rate limiting

`POST /search` and `POST /questions` share one allowance per client IP: by default,
3 requests in any rolling 60-second window. Two searches and one question use the
same allowance. Requests rejected by the dependency do not reach retrieval,
Voyage, or Groq. Attempts that reach the dependency count even if they later fail.

An excess request returns `429 Too Many Requests`:

```json
{"detail": "Too many requests. Please try again later."}
```

The `Retry-After` header contains the number of seconds to wait. Rejected attempts
do not extend the waiting period. Health checks, API documentation, and library
listing are not subject to this limit. Upload and deletion require administrator
authentication instead.

`rate_limit.py` implements a small sliding window using standard-library data
structures, a monotonic clock, and a lock for concurrent requests. It requires no
new package, database table, daily counter, or budget per provider. Inactive client
entries expire. Storage is capped at 10,000 active IPs; new IPs are temporarily
rejected if that capacity is full, instead of evicting active counters.

Counters live in memory and reset when the server restarts. Run a single Uvicorn
worker for this MVP: multiple processes or servers would each have their own
allowance. Shared storage or proxy-level limiting can be added if that changes.
People sharing a public IP also share an allowance; distributed clients can have
separate allowances. This is basic abuse protection, not a global spending cap.

The limiter uses `request.client.host` and does not directly trust forwarded
headers. For the VPS reverse proxy, configure Uvicorn to trust only the actual
proxy address and have the proxy overwrite client-supplied forwarding headers.
Otherwise clients could share the proxy IP or spoof their identity. For a local
reverse proxy connected over IPv4 loopback, the server options will include
`--proxy-headers --forwarded-allow-ips=127.0.0.1`; do not trust arbitrary proxies.

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
requests are sent with `truncation: false`, so the provider rejects oversized
inputs instead of silently removing text. No local tokenizer or model is loaded.

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
| `chunks` | `id`, `document_id`, `chunk_index`, `page_number`, `text`, `embedding` | Text passages and their embeddings |

Each chunk belongs to a document. The database prevents duplicate chunk indices
within a document and automatically removes its chunks when the document is
deleted. The unique `(document_id, chunk_index)` index also supports lookups by
document. No vector search index is needed at this stage.

`embedding` is a `vector(1024)` column matching the selected Voyage model.
The schema remains nullable for compatibility with earlier development data, but
the repository now requires a matching 1024-dimensional vector for every chunk
before inserting anything. It rejects inconsistent counts, sizes, and non-finite
numbers. New uploads always populate all chunk embeddings.

For databases created before step 8, reapply the same initialization file from
the project root to set the embedding size:

```bash
docker compose exec -T db sh -c 'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < backend/sql/001_init.sql
```

The initialization file is transactional and safe to reapply. Existing tables
are preserved, and incompatible vectors cause a rollback rather than deletion or
truncation. Fresh databases use 1024 dimensions from their first initialization.

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

## Voyage embeddings

The selected model is **`voyage-4-lite`**, using **1024-dimensional float vectors**.
It supports multilingual retrieval and keeps costs low for this MVP.
The model and dimensions are fixed in `config.py` to match the database column.
Changing them later requires checking compatibility and reindexing documents.

As checked on October 21, 2026, Voyage lists an initial allowance of **200 million
free tokens** for this model and a subsequent price of **$0.02 per million tokens**.
This is an initial allowance, not a monthly quota. Existing usage and account
eligibility determine the remaining balance; rate limits still apply. Check the
[official pricing](https://docs.voyageai.com/docs/pricing) and your dashboard.

1. Create a key in the [Voyage dashboard](https://dash.voyageai.com/).
2. Set `VOYAGE_API_KEY` in your local `.env` file. Do not share or commit it.
3. With the virtual environment active, explicitly run a small live request:

```bash
PYTHONPATH=backend python -m app.embeddings
```

The command sends one short example passage and prints only the model name,
number of vectors, dimensions, and consumed tokens. It does not print the key or
the full vector and does not write to PostgreSQL. Without a key, it exits with a
clear message before making any network call. This is an explicit live check;
the normal test suite never calls Voyage.

`embeddings.py` provides:

- `embed_documents(texts, settings)` for chunks, using `input_type="document"`.
- `embed_query(question, settings)` for a question, using `input_type="query"`.

Both return an `EmbeddingResult` with `embeddings`, `total_tokens`, `model`, and
`dimensions`. A query returns one vector in the `embeddings` list. Documents and
queries always use the same model and dimension. The code uses HTTPX to call the
[official REST endpoint](https://docs.voyageai.com/reference/embeddings-api)
directly, keeping HTTP requests visible for learning and avoiding a local model
or tokenizer dependency.

Requests are sent sequentially in small batches. Response indices are checked and
reordered to match the input; each vector must have exactly 1024 finite numbers.
Token usage is summed across successful batches. Empty document lists return an
empty result without an API call; blank passages and questions are rejected.

Missing credentials, authentication errors, rate limits, invalid inputs, timeouts,
network errors, and malformed responses produce explicit `EmbeddingError`
messages without exposing credentials or raw provider responses. No automatic
retries are performed at this stage. If a later batch fails, the operation raises
an error instead of returning partial results; earlier successful requests can
still consume tokens. The provider enforces actual token limits. The application
does not track the account-wide free allowance or automatically stop at its end.

Uploading a PDF now calls `embed_documents()` and persists the returned vectors.
`embed_query()` embeds questions for `POST /search`. No separate public endpoint
for arbitrary embedding requests has been added.

## Python database access

`database.py` opens synchronous Psycopg connections with parameterized connection
arguments, dictionary results, a 3-second connection timeout, and a 5-second SQL
statement timeout. The password is held in a Pydantic `SecretStr` so it is masked
in the settings representation.

Use a connection in a `with` block. Psycopg commits on success, rolls back on an
exception, and closes the connection when the block ends. `repository.py` provides:

- `create_document(connection, filename, page_count, chunks, embeddings)` to save metadata,
  chunks, and vectors together in a transaction. A failed chunk insert rolls back the
  document insert as well. With an already active transaction, it uses a savepoint;
  the outer transaction still controls the final commit.
- `get_document(connection, document_id)` to read metadata or return `None`.
- `get_document_chunks(connection, document_id)` to read passages in index order.
- `list_documents(connection, limit, offset)` to read public library summaries.
- `delete_document(connection, document_id)` to remove a document and cascade to
  its chunks; it returns whether a document was found.
- `search_chunks(connection, document_id, query_embedding, top_k)` to retrieve
  the nearest passages and their cosine similarities within a document.

All SQL values are passed as parameters, including filenames, vectors, and document IDs.
Vectors are serialized to JSON lists and bound as parameters cast to `vector`.
Connection failures are re-raised with a generic message and their driver
tracebacks suppressed, because those frames can contain plaintext credentials.
Connections are opened only when needed; no pool or ORM is used in this MVP.

`GET /health/db` checks connectivity, the pgvector extension, and the presence of
the public `documents` and `chunks` tables. It returns `200` with `{"status":"ok"}`
when ready, or `503` with a generic error if the database is unavailable or not
initialized. Credentials and database errors are not returned to visitors.
`GET /health` still works while PostgreSQL is stopped. Upload, listing, deletion, and search
require PostgreSQL.

The filename must end with `.pdf` (case-insensitive). The backend also checks
the PDF header and parses the content; it does not trust the MIME type alone.

| Status | Meaning |
|---|---|
| `400` | Empty uploaded file |
| `413` | File size or page limit exceeded |
| `415` | Unsupported filename extension |
| `422` | Missing file, invalid PDF, encrypted PDF, or no extractable text |
| `502` | Voyage embedding operation failed; nothing was saved |
| `503` | Database unavailable, not initialized, or write operation failed |

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
│   ├── auth.py          # Administrator key dependency for library mutations
│   ├── config.py        # Environment settings and validation
│   ├── chunking.py      # Character-based chunking with overlap
│   ├── database.py      # Psycopg connections and readiness check
│   ├── embeddings.py    # Voyage API client and explicit live check
│   ├── generation.py    # Groq client, prompt, and citation validation
│   ├── main.py          # Application and HTTP endpoints
│   ├── pdf.py           # PDF parsing and text extraction
│   ├── questions.py     # Retrieval, context budget, and answer sources
│   ├── rate_limit.py    # Shared in-memory per-IP search/question limit
│   ├── repository.py    # Parameterized SQL for documents and chunks
│   ├── retrieval.py     # Question embedding and passage retrieval
│   └── schemas.py       # API response models
├── sql/
│   └── 001_init.sql     # Extension, tables, constraints, and embedding size
├── tests/
│   ├── conftest.py      # Test client and generated PDF fixtures
│   ├── test_auth.py
│   ├── test_config.py
│   ├── test_chunking.py
│   ├── test_database.py
│   ├── test_embeddings.py
│   ├── test_generation.py
│   ├── test_library.py
│   ├── test_search.py
│   ├── test_questions.py
│   ├── test_rate_limit.py
│   └── test_documents.py
├── requirements.txt
└── requirements-dev.txt
```

Request flow: `main.py` checks the upload, `pdf.py` extracts the pages,
`chunking.py` creates the chunks, and `schemas.py` defines the JSON response.
`embeddings.py` requests the vectors, then `repository.py` saves the document,
chunks, and vectors through `database.py`. `config.py` supplies the settings.
For search, `main.py` validates the request and calls `retrieval.py`, which checks
the document, embeds the question, and calls `repository.search_chunks()`.
For answers, `questions.py` reuses retrieval and builds the context; `generation.py`
calls Groq and validates citations before source metadata is returned.
The extraction function is synchronous; the endpoint uses `def` so FastAPI runs
it in a thread pool rather than directly blocking the async event loop.

## Run backend tests

From the project root, with the virtual environment activated:

```bash
python -m pip install -r backend/requirements-dev.txt
python -m pytest -q
```

Tests generate small real PDFs in memory. They cover extraction, page numbering,
blank pages, invalid and encrypted files, upload limits, missing files, and
configuration loading and validation. Chunking tests cover overlap, text coverage,
page boundaries, empty pages, Unicode text, and the configured upload response.
Voyage calls are simulated using HTTPX MockTransport, including batching, query
and document modes, index ordering, invalid vectors, and provider failures.
Groq calls are also simulated with HTTPX MockTransport. Tests cover grounded
responses, abstention, invented/missing citations, malformed or truncated output,
provider errors, context budgets, key masking, and source metadata mapping.
Rate limit tests use a fake clock and simulated route handlers. They cover the
shared allowance, retry delays, expiry, concurrent requests, bounded storage,
separate clients, and rejection of forged forwarding headers without API calls.
Authentication tests cover missing, invalid, and valid keys, disabled server
configuration, public routes, OpenAPI security declarations, and blocked side
effects. Business-logic tests bypass authentication explicitly; a separate real
database test verifies authenticated mutations without bypassing the dependency.
No external APIs are required. The default test run skips the eighteen database
integration tests. To run the full suite with the project's PostgreSQL running:

```bash
docker compose up -d --wait db
python -m pytest -q --run-db-tests
```

Integration tests create and remove isolated temporary schemas in the configured
local database. They do not modify the public library. They verify committed
writes across connections, reads, rollback on failure, cascade deletion, table
constraints, synthetic vectors, and safe dimension migration. Database readiness error responses
are also tested without requiring PostgreSQL.
API integration tests exercise indexing, listing, pagination, cascading deletion,
and rollback behavior with real PostgreSQL and simulated Voyage responses.
Search tests verify cosine ranking, document isolation, result limits, skipping
null/zero vectors, request validation, missing documents, concurrent deletion,
and safe errors. They use controlled synthetic vectors and real pgvector SQL.
The real Voyage smoke check used only a short fictional passage in an isolated
temporary schema, which was removed afterward; it is not part of the normal suite.
A full question integration test exercises PDF indexing, real pgvector retrieval,
prompt construction, simulated Groq generation, and returned citations together.

## Continuous integration (CI)

The GitHub Actions workflow in `.github/workflows/ci.yml` runs on pull requests
and pushes to `main`. It has two jobs:

1. Run the backend tests using a temporary PostgreSQL database with pgvector.
2. Install the frontend dependencies and build the React application.

No frontend tests, real Voyage/Groq calls, or project secrets are needed.
The workflow does not publish Docker images or deploy to the VPS. Deployment
remains manual using [the deployment guide](deploy/DEPLOYMENT.md): Docker builds
and runs the application on the VPS. Python and Node are provided by the Docker
images, so they do not need to be installed separately on the VPS.

The first CI run will happen after this file is pushed to GitHub.

## Next steps

1. Project owner: publish the changes and deploy using `deploy/DEPLOYMENT.md`.
2. Project owner: validate the site using `docs/MANUAL_CHECKS.md`, including real Qwen answers.
3. Review any reported issues before final handoff.

## Learning follow-up before final project handoff

- [ ] Revisit `rate_limit.py` with the project owner after the project is complete.
  Explain `self`, the `check()` method, and sliding windows slowly using a concrete
  request timeline. This explanation was explicitly postponed until the end.
