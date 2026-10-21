from app.config import LLM_MODEL, Settings
from app.generation import INSUFFICIENT_CONTEXT, generate_answer, require_groq_key
from app.retrieval import retrieve_passages
from app.schemas import AnswerSource, QuestionRequest, QuestionResponse


def answer_question(request: QuestionRequest, settings: Settings) -> QuestionResponse:
    """Retrieve passages, limit the context, and return an answer with real sources."""
    # Avoid spending Voyage tokens if generation cannot be configured.
    require_groq_key(settings)
    retrieval = retrieve_passages(request, settings)
    sources = []
    remaining = settings.llm_max_context_chars
    for match in retrieval.matches:
        if remaining <= 0:
            break
        text = match.text[:remaining]
        if not text.strip():
            continue
        sources.append(AnswerSource(
            **{**match.model_dump(), "text": text},
            source_id=len(sources) + 1,
            document_id=retrieval.document_id,
            filename=retrieval.filename,
        ))
        remaining -= len(text)

    result = generate_answer(request.question, sources, settings) if sources else None
    cited_ids = set(result.source_ids) if result else set()
    return QuestionResponse(
        document_id=retrieval.document_id,
        filename=retrieval.filename,
        question=retrieval.question,
        answer=result.answer if result else INSUFFICIENT_CONTEXT,
        answerable=result.answerable if result else False,
        sources=[source for source in sources if source.source_id in cited_ids],
        embedding_tokens=retrieval.embedding_tokens,
        llm_model=LLM_MODEL if result else None,
        llm_usage=result.usage if result else None,
    )
