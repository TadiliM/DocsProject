from psycopg import Connection

from app.schemas import DocumentChunk, StoredChunk, StoredDocument


def create_document(
    connection: Connection,
    filename: str,
    page_count: int,
    chunks: list[DocumentChunk],
) -> StoredDocument:
    """Insert a document and its chunks atomically, without embeddings yet."""
    if not chunks:
        raise ValueError("A document must contain at least one chunk.")

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
                INSERT INTO chunks (document_id, chunk_index, page_number, text)
                VALUES (%s, %s, %s, %s)
                """,
                [
                    (row["id"], chunk.chunk_index, chunk.page_number, chunk.text)
                    for chunk in chunks
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
