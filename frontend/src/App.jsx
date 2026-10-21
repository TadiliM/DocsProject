import { useEffect, useState } from "react";

function AnswerText({ answer, sources }) {
  const sourceIds = new Set(sources.map((source) => source.source_id));
  return answer.split(/(\[\d+\])/).map((part, index) => {
    const match = part.match(/^\[(\d+)\]$/);
    if (match && sourceIds.has(Number(match[1]))) {
      return <a key={index} href={`#source-${match[1]}`} aria-label={`Read source ${match[1]}`}>{part}</a>;
    }
    return part;
  });
}

export default function App() {
  const [documents, setDocuments] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [loadingDocuments, setLoadingDocuments] = useState(true);
  const [libraryError, setLibraryError] = useState("");
  const [questionError, setQuestionError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [retryIn, setRetryIn] = useState(0);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingDocuments(true);
    setLibraryError("");

    async function loadDocuments() {
      try {
        const response = await fetch("/api/documents?limit=100", { signal: controller.signal });
        if (!response.ok) throw new Error("The document library is unavailable. Please try again.");
        const data = await response.json();
        if (!Array.isArray(data)) throw new Error("The document library could not be loaded.");
        setDocuments(data);
        setSelectedId((current) => data.some((doc) => String(doc.id) === current) ? current : String(data[0]?.id ?? ""));
      } catch (error) {
        if (error.name !== "AbortError") {
          setLibraryError(error instanceof TypeError ? "Could not reach the document library. Please try again." : error.message);
        }
      } finally {
        if (!controller.signal.aborted) setLoadingDocuments(false);
      }
    }

    loadDocuments();
    return () => controller.abort();
  }, [reload]);

  useEffect(() => {
    if (retryIn <= 0) return;
    const timer = setTimeout(() => setRetryIn((seconds) => seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [retryIn]);

  async function submitQuestion(event) {
    event.preventDefault();
    if (!selectedId || !question.trim() || submitting || retryIn > 0) return;
    setSubmitting(true);
    setQuestionError("");
    setResult(null);
    try {
      const response = await fetch("/api/questions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: Number(selectedId), question: question.trim() }),
      });
      if (response.status === 429) {
        const seconds = Number(response.headers.get("Retry-After"));
        setRetryIn(Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : 60);
        throw new Error("You have sent too many questions. Please wait before trying again.");
      }
      if (response.status === 404) throw new Error("This document is no longer available. Reload the library.");
      if (response.status === 502 || response.status === 503) {
        throw new Error("The answer service is temporarily unavailable. Please try again later.");
      }
      if (!response.ok) throw new Error("Your question could not be processed. Please try again.");
      const data = await response.json();
      if (typeof data.answer !== "string" || !Array.isArray(data.sources) || typeof data.answerable !== "boolean") {
        throw new Error("The answer could not be read. Please try again.");
      }
      setResult(data);
    } catch (error) {
      setQuestionError(error instanceof TypeError
        ? "Could not reach the server. Check your connection and try again."
        : error instanceof SyntaxError ? "The answer could not be read. Please try again." : error.message);
    } finally {
      setSubmitting(false);
    }
  }

  function selectDocument(event) {
    setSelectedId(event.target.value);
    setResult(null);
    setQuestionError("");
  }

  return (
    <main>
      <header>
        <h1>DocsProject</h1>
        <p>Ask questions about public PDF documents and see where the answers come from.</p>
      </header>

      <section className="card" aria-labelledby="question-heading">
        <h2 id="question-heading">Ask a question</h2>
        {loadingDocuments ? <p role="status">Loading documents…</p> : libraryError ? (
          <div>
            <p className="error" role="alert">{libraryError}</p>
            <button type="button" onClick={() => setReload((value) => value + 1)}>Try again</button>
          </div>
        ) : documents.length === 0 ? (
          <p>No documents are available yet. Please check back later.</p>
        ) : (
          <form onSubmit={submitQuestion}>
            <label htmlFor="document">Document</label>
            <select id="document" value={selectedId} onChange={selectDocument} disabled={submitting} required>
              {documents.map((document) => (
                <option key={document.id} value={document.id}>
                  {document.filename} ({document.page_count} {document.page_count === 1 ? "page" : "pages"})
                </option>
              ))}
            </select>
            <label htmlFor="question">Your question</label>
            <textarea
              id="question" rows={4} maxLength={2000} required
              placeholder="e.g. What is this document about?"
              value={question} onChange={(event) => setQuestion(event.target.value)}
              disabled={submitting} aria-describedby="question-help"
            />
            <p id="question-help" className="hint">Each question is independent. Previous answers are not remembered.</p>
            <div className="actions">
              <button type="submit" disabled={submitting || !question.trim() || retryIn > 0}>
                {submitting ? "Finding an answer…" : retryIn > 0 ? `Try again in ${retryIn}s` : "Ask question"}
              </button>
              <button type="button" className="secondary" disabled={submitting} onClick={() => {
                setResult(null);
                setQuestionError("");
                setReload((value) => value + 1);
              }}>Reload library</button>
            </div>
          </form>
        )}
        {questionError && <p className="error" role="alert">{questionError}</p>}
        {submitting && <p className="hint" role="status">Reading the relevant passages. This may take a moment.</p>}
      </section>

      {result && (
        <section className="card" aria-labelledby="answer-heading" aria-live="polite">
          <h2 id="answer-heading">{result.answerable ? "Answer" : "Not enough information"}</h2>
          <p className="hint">{result.question}</p>
          <p className="answer"><AnswerText answer={result.answer} sources={result.sources} /></p>
          {result.sources.length > 0 && (
            <div className="sources">
              <h3>Sources</h3>
              {result.sources.map((source) => (
                <article className="source" id={`source-${source.source_id}`} key={source.source_id} tabIndex={-1}>
                  <h4>[{source.source_id}] {source.filename} — Page {source.page_number}</h4>
                  <blockquote>{source.text}</blockquote>
                </article>
              ))}
            </div>
          )}
        </section>
      )}
      <footer>A small document Q&amp;A project. Check the source passages when reviewing an answer.</footer>
    </main>
  );
}
