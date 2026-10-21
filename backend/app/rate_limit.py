from collections import OrderedDict, deque
from math import ceil
from threading import Lock
from time import monotonic
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Request

from app.config import Settings, get_settings


class SlidingWindowLimiter:
    """Keep recent request times per client in this server process only."""

    def __init__(self, clock: Callable[[], float] = monotonic, max_clients: int = 10000):
        self.clock = clock
        self.max_clients = max_clients
        self.clients: OrderedDict[str, deque[float]] = OrderedDict()
        self.lock = Lock()

    def check(self, client: str, limit: int, window_seconds: int) -> int:
        """Return zero if allowed, or the number of seconds before retrying."""
        with self.lock:
            now = self.clock()
            cutoff = now - window_seconds

            # Clients are ordered by their last accepted request. Remove inactive
            # clients before storing new ones, so memory does not grow forever.
            while self.clients:
                oldest = next(iter(self.clients.values()))
                if oldest[-1] > cutoff:
                    break
                self.clients.popitem(last=False)

            times = self.clients.get(client)
            if times is None:
                if len(self.clients) >= self.max_clients:
                    oldest = next(iter(self.clients.values()))
                    return max(1, ceil(oldest[-1] + window_seconds - now))
                times = deque()
                self.clients[client] = times

            while times and times[0] <= cutoff:
                times.popleft()
            if len(times) >= limit:
                return max(1, ceil(times[0] + window_seconds - now))

            times.append(now)
            self.clients.move_to_end(client)
            return 0


def enforce_rate_limit(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    # Forwarded headers must be handled by Uvicorn's trusted-proxy configuration,
    # not trusted directly from arbitrary request headers in application code.
    client = request.client.host if request.client else "unknown"
    retry_after = request.app.state.rate_limiter.check(
        client, settings.rate_limit_requests, settings.rate_limit_window_seconds
    )
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
