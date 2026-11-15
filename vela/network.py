"""Vela's read-only provider requests: one shared connection pool, bounded retries,
and a small in-memory cache for answers that can be reused for a few minutes."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable
from typing import Any

import httpx


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

# The providers are far away: a new HTTPS connection costs about a second before any
# data moves. Connections are kept open and reused, across requests and threads.
KEEPALIVE_SECONDS = 60.0
# Setting up a connection (TCP plus TLS) normally takes under a second; the slowest
# healthy one measured took about 4 s. Past this, a handshake has usually stalled and
# will not finish, so give up and retry on a fresh connection instead of waiting out
# the full allowance meant for a slow answer.
CONNECT_TIMEOUT_SECONDS = 5.0

_client: httpx.Client | None = None
_client_lock = threading.Lock()


def shared_client() -> httpx.Client:
    """The process-wide client. httpx clients are safe to share between threads."""

    global _client
    with _client_lock:
        if _client is None or _client.is_closed:
            _client = httpx.Client(
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=40,
                    max_keepalive_connections=20,
                    keepalive_expiry=KEEPALIVE_SECONDS,
                ),
            )
        return _client


def _split_timeout(timeout: float | httpx.Timeout) -> httpx.Timeout:
    if isinstance(timeout, httpx.Timeout):
        return timeout
    return httpx.Timeout(float(timeout), connect=min(float(timeout), CONNECT_TIMEOUT_SECONDS))


class TtlCache:
    """Keeps loaded values for a short time. Simultaneous callers of one key share one load."""

    def __init__(self, max_items: int = 512, clock: Callable[[], float] = time.monotonic):
        self._max_items = max_items
        self._clock = clock
        self._items: dict[Hashable, tuple[float, Any]] = {}
        self._loading: dict[Hashable, threading.Lock] = {}
        self._guard = threading.Lock()

    def __len__(self) -> int:
        return len(self._items)

    def _fresh(self, key: Hashable):
        hit = self._items.get(key)
        if hit is not None and hit[0] > self._clock():
            return hit
        return None

    def get_or_load(
        self,
        key: Hashable,
        ttl_seconds: float,
        load: Callable[[], Any],
        keep: Callable[[Any], bool] = lambda _value: True,
    ) -> Any:
        """Return a fresh stored value, or load one. Only values `keep` accepts are stored."""

        with self._guard:
            hit = self._fresh(key)
            if hit is not None:
                return hit[1]
            loading = self._loading.setdefault(key, threading.Lock())
        with loading:
            with self._guard:
                hit = self._fresh(key)
            if hit is not None:
                return hit[1]
            try:
                value = load()
                if keep(value):
                    with self._guard:
                        self._store(key, ttl_seconds, value)
                return value
            finally:
                # Released only after the value is stored, so a waiting caller finds it.
                with self._guard:
                    if self._loading.get(key) is loading:
                        del self._loading[key]

    def _store(self, key: Hashable, ttl_seconds: float, value: Any) -> None:
        if len(self._items) >= self._max_items:
            now = self._clock()
            for stale in [k for k, (expires, _) in self._items.items() if expires <= now]:
                del self._items[stale]
        while len(self._items) >= self._max_items:
            del self._items[next(iter(self._items))]
        self._items[key] = (self._clock() + ttl_seconds, value)


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Use a short Retry-After when supplied, otherwise exponential backoff."""

    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), 2.0)
            except ValueError:
                pass
    return min(0.25 * (2**attempt), 1.0)


def retrying_get(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    auth: Any = None,
    timeout: float | httpx.Timeout = 30.0,
    attempts: int = 3,
    before_attempt: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Response:
    """GET with TLS verification and bounded retries for transient failures.

    Requests go through the shared keep-alive client. A `transport` (tests) gets a
    private client that is closed afterwards.
    """

    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    request_timeout = _split_timeout(timeout)
    private = None if transport is None else httpx.Client(follow_redirects=True, transport=transport)
    client = private or shared_client()
    try:
        for attempt in range(attempts):
            if before_attempt is not None:
                before_attempt()
            response = None
            try:
                response = client.get(url, params=params, headers=headers, auth=auth, timeout=request_timeout)
            except httpx.TransportError:
                if attempt + 1 >= attempts:
                    raise
            else:
                if response.status_code not in RETRYABLE_STATUS_CODES or attempt + 1 >= attempts:
                    return response
                response.close()

            sleep(_retry_delay(response, attempt))
    finally:
        if private is not None:
            private.close()

    raise RuntimeError("HTTP retry loop ended unexpectedly")
