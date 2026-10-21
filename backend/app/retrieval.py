from app.config import Settings
from app.database import get_connection
from app.embeddings import embed_query
from app.repository import get_document, search_chunks
from app.schemas import SearchRequest, SearchResponse


class DocumentNotFoundError(LookupError):
    """The selected document does not exist."""


def retrieve_passages(request: SearchRequest, settings: Settings) -> SearchResponse:
    """Embed the question and retrieve passages without generating an answer."""
    # Check existence before spending tokens. Close the connection before Voyage.
    with get_connection(settings) as connection:
        document = get_document(connection, request.document_id)
    if document is None:
        raise DocumentNotFoundError("Document not found.")

    result = embed_query(request.question, settings)

    with get_connection(settings) as connection:
        # A document may have been deleted while the external call was running.
        document = get_document(connection, request.document_id)
        if document is None:
            raise DocumentNotFoundError("Document not found.")
        matches = search_chunks(
            connection, document.id, result.embeddings[0], request.top_k
        )

    return SearchResponse(
        document_id=document.id,
        filename=document.filename,
        question=request.question,
        matches=matches,
        embedding_tokens=result.total_tokens,
    )
