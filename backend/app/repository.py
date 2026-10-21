import json

from psycopg import Connection

from app.config import EMBEDDING_DIMENSIONS
from app.schemas import DocumentChunk, DocumentSummary, SearchMatch, StoredChunk, StoredDocument


def create_document(
    connection: Connection,
    filename: str,
    page_count: int,
    chunks: list[DocumentChunk],
    embeddings: list[list[float]],
) -> StoredDocument:
    """Insert a document, its chunks, and their vectors in one transaction."""
    if not chunks:
        raise ValueError("A document must contain at least one chunk.")
    if len(chunks) != len(embeddings):
        raise ValueError("Each chunk must have exactly one embedding.")
    if any(len(vector) != EMBEDDING_DIMENSIONS for vector in embeddings):
        raise ValueError(f"Embeddings must have {EMBEDDING_DIMENSIONS} dimensions.")
    vectors = [json.dumps(vector, allow_nan=False) for vector in embeddings]

    with connection.transaction():
        row = connection.execute(
            """
            INSERT INTO documents (filename, page_count)
            VALUES (%s, %s)
            RETURNING id, filename, page_count, created_at
            """,
            (filename, page_count),
        ).fetchone()

        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO chunks (document_id, chunk_index, page_number, text, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                """,
                [
                    (row["id"], chunk.chunk_index, chunk.page_number, chunk.text, vector)
                    for chunk, vector in zip(chunks, vectors)
                ],
            )

        return StoredDocument(**row)


def get_document(connection: Connection, document_id: int) -> StoredDocument | None:
    row = connection.execute(
        """
        SELECT id, filename, page_count, created_at
        FROM documents WHERE id = %s
        """,
        (document_id,),
    ).fetchone()
    return StoredDocument(**row) if row else None


def get_document_chunks(connection: Connection, document_id: int) -> list[StoredChunk]:
    rows = connection.execute(
        """
        SELECT id, document_id, chunk_index, page_number, text
        FROM chunks WHERE document_id = %s ORDER BY chunk_index
        """,
        (document_id,),
    ).fetchall()
    return [StoredChunk(**row) for row in rows]


def list_documents(
    connection: Connection, limit: int = 100, offset: int = 0
) -> list[DocumentSummary]:
    rows = connection.execute(
        """
        SELECT d.id, d.filename, d.page_count, d.created_at, COUNT(c.id) AS chunk_count
        FROM documents AS d
        LEFT JOIN chunks AS c ON c.document_id = d.id
        GROUP BY d.id
        ORDER BY d.created_at DESC, d.id DESC
        LIMIT %s OFFSET %s
        """,
        (limit, offset),
    ).fetchall()
    return [DocumentSummary(**row) for row in rows]


def delete_document(connection: Connection, document_id: int) -> bool:
    """Delete a document; PostgreSQL cascades the deletion to its chunks."""
    row = connection.execute(
        "DELETE FROM documents WHERE id = %s RETURNING id", (document_id,)
    ).fetchone()
    return row is not None


def search_chunks(
    connection: Connection, document_id: int, query_embedding: list[float], top_k: int
) -> list[SearchMatch]:
    """Find the closest passages within one document using cosine distance."""
    if len(query_embedding) != EMBEDDING_DIMENSIONS or not any(query_embedding):
        raise ValueError("The query embedding must be a nonzero 1024-dimensional vector.")
    vector = json.dumps(query_embedding, allow_nan=False)
    rows = connection.execute(
        """
        SELECT id AS chunk_id, chunk_index, page_number, text,
               1 - (embedding <=> %s::vector) AS similarity
        FROM chunks
        WHERE document_id = %s
          AND embedding IS NOT NULL
          AND vector_norm(embedding) > 0
        ORDER BY embedding <=> %s::vector, chunk_index
        LIMIT %s
        """,
        (vector, document_id, vector, top_k),
    ).fetchall()
    return [SearchMatch(**row) for row in rows]
