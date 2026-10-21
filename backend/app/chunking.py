from app.schemas import DocumentChunk, PageText


def chunk_pages(
    pages: list[PageText], chunk_size: int, chunk_overlap: int
) -> list[DocumentChunk]:
    """Split each page into character windows without crossing page boundaries."""
    if chunk_size < 1 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("Chunk size must be positive and overlap must be in [0, size).")

    chunks = []
    for page in pages:
        text = page.text.strip()
        start = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))
            passage = text[start:end].strip()
            if passage:
                chunks.append(
                    DocumentChunk(
                        chunk_index=len(chunks),
                        page_number=page.page_number,
                        text=passage,
                    )
                )

            if end == len(text):
                break
            start = end - chunk_overlap

    return chunks
