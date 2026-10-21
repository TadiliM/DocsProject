from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from app.config import Settings, get_settings
from app.main import app
from app.rate_limit import SlidingWindowLimiter
from app.retrieval import DocumentNotFoundError


def test_sliding_window_and_retry_delay():
    now = [0.0]
    limiter = SlidingWindowLimiter(clock=lambda: now[0])
    assert limiter.check("client", 2, 60) == 0
    now[0] = 10
    assert limiter.check("client", 2, 60) == 0
    now[0] = 20
    assert limiter.check("client", 2, 60) == 40
    now[0] = 60
    assert limiter.check("client", 2, 60) == 0
    assert limiter.check("client", 2, 60) == 10


def test_separate_clients_have_separate_limits():
    limiter = SlidingWindowLimiter(clock=lambda: 0)
    assert limiter.check("first", 1, 60) == 0
    assert limiter.check("first", 1, 60) == 60
    assert limiter.check("second", 1, 60) == 0


def test_concurrent_requests_cannot_exceed_the_limit():
    limiter = SlidingWindowLimiter(clock=lambda: 0)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: limiter.check("client", 3, 60), range(20)))
    assert results.count(0) == 3
    assert results.count(60) == 17


def test_inactive_clients_expire_and_capacity_is_bounded():
    now = [0.0]
    limiter = SlidingWindowLimiter(clock=lambda: now[0], max_clients=2)
    assert limiter.check("first", 3, 60) == 0
    assert limiter.check("second", 3, 60) == 0
    assert limiter.check("third", 3, 60) == 60
    assert len(limiter.clients) == 2
    now[0] = 60
    assert limiter.check("third", 3, 60) == 0
    assert list(limiter.clients) == ["third"]


@pytest.fixture
def limited_routes(client, monkeypatch):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, rate_limit_requests=2, rate_limit_window_seconds=60,
    )
    now = [0.0]
    app.state.rate_limiter = SlidingWindowLimiter(clock=lambda: now[0])
    search = Mock(side_effect=DocumentNotFoundError())
    questions = Mock(side_effect=DocumentNotFoundError())
    monkeypatch.setattr("app.main.retrieve_passages", search)
    monkeypatch.setattr("app.main.answer_question", questions)
    return now, search, questions


def test_both_routes_share_one_limit_and_block_before_providers(client, limited_routes):
    now, search, questions = limited_routes
    body = {"document_id": 1, "question": "Question?"}
    assert client.post("/search", json=body).status_code == 404
    assert client.post("/questions", json=body).status_code == 404

    response = client.post("/questions", json=body)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert response.json() == {"detail": "Too many requests. Please try again later."}
    assert search.call_count == 1
    assert questions.call_count == 1
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200

    now[0] = 60
    assert client.post("/questions", json=body).status_code == 404
    assert questions.call_count == 2


def test_forwarded_header_cannot_bypass_limit(client, limited_routes):
    body = {"document_id": 1, "question": "Question?"}
    for ip in ["198.51.100.1", "198.51.100.2"]:
        assert client.post("/search", json=body, headers={"X-Forwarded-For": ip}).status_code == 404
    response = client.post("/search", json=body, headers={"X-Forwarded-For": "198.51.100.3"})
    assert response.status_code == 429
