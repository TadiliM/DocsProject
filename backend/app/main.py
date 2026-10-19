from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(
    title="DocsProject API",
    description="Search API for a public PDF library.",
    version="0.1.0",
)


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Check that the API is responding."""
    return HealthResponse(status="ok")
