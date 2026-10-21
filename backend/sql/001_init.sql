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
    -- The embedding model and its dimensions will be selected in step 8.
    embedding VECTOR,
    UNIQUE (document_id, chunk_index)
);
