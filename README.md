# DocsProject — AI Document Search

A learning project: build an application that answers questions about PDF documents
and displays the source passages. The priority is understanding the Python backend.

## Design decisions

- A public library: all visitors query the same documents.
- Document uploads and deletions are restricted to the administrator. Access must
  be protected before deployment.
- Text-based PDFs only, without OCR.
- Each question targets one selected document, without conversation memory.
- Python backend using FastAPI and Pydantic, served by Uvicorn.
- PostgreSQL and pgvector for documents, passages, and vectors.
- External APIs for embeddings and answer generation. No models run locally.
- Eventually: a simple React frontend and deployment to a VPS.

## Current status: step 1

The API starts and exposes `GET /health`. PDF processing, database storage,
model API calls, and the frontend will be added incrementally.

## Run the backend

Requires Python 3.10 or newer. From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python -m uvicorn app.main:app --app-dir backend --reload
```

If `python3` is too old, use a newer executable to create the environment,
for example `python3.12 -m venv .venv`.

- Health check: http://127.0.0.1:8000/health
- Interactive API documentation: http://127.0.0.1:8000/docs

Expected response from `/health`:

```json
{"status": "ok"}
```

This endpoint only checks that the API responds. It does not check a database
connection or a model provider.

## Project structure

```text
backend/
├── app/
│   ├── __init__.py       # Declares the app Python package
│   └── main.py           # FastAPI application, response model, and health endpoint
└── requirements.txt      # Backend Python dependencies
```

Uvicorn receives HTTP requests and calls the `app` application in the `app.main`
module. FastAPI selects the route; Pydantic defines the response format.
The `--reload` option is for development and will not be used in production.

## Next steps

1. Accept a PDF and extract text page by page using pypdf.
2. Split the text into passages.
3. Request embeddings from an API and store passages in PostgreSQL.
4. Retrieve relevant passages for a question.
5. Generate an answer with sources.
6. Add the frontend, protect administrative operations, and prepare VPS deployment.
