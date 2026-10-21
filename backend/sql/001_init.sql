BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    filename TEXT NOT NULL CHECK (length(trim(filename)) > 0),
    page_count INTEGER NOT NULL CHECK (page_count > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    text TEXT NOT NULL CHECK (length(trim(text)) > 0),
    -- voyage-4-lite uses 1024-dimensional float embeddings in this project.
    embedding VECTOR(1024),
    UNIQUE (document_id, chunk_index)
);

-- Also update databases initialized before the embedding size was fixed.
-- Incompatible existing vectors abort the transaction without losing data.
ALTER TABLE chunks
    ALTER COLUMN embedding TYPE VECTOR(1024)
    USING embedding::VECTOR(1024);

COMMIT;
