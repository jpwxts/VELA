"""Vela's read-only provider requests: one shared connection pool, bounded retries,
and a short pause for providers that cannot be reached at all."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
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
# When a provider cannot be connected to at all (every attempt of a request failed to
# connect), it is left alone for this long: requests to it fail at once instead of each
# spending the whole retry budget (3 x 5 s) failing the same way. After the pause, one
# attempt checks whether it is back.
UNREACHABLE_PAUSE_SECONDS = 60.0
# Within this window after a failure, a check is a single attempt rather than three.
RECOVERY_WINDOW_SECONDS = 10 * 60.0
_CONNECT_FAILURES = (httpx.ConnectError, httpx.ConnectTimeout)

_clock: Callable[[], float] = time.monotonic
_failed_at: dict[str, float] = {}
_failed_lock = threading.Lock()

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

    Requests go through the shared keep-alive client, and a provider that could not be
    connected to at all is paused (see UNREACHABLE_PAUSE_SECONDS). A `transport` (tests)
    gets a private client that is closed afterwards and is not paused.
    """

    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    request_timeout = _split_timeout(timeout)
    private = None if transport is None else httpx.Client(follow_redirects=True, transport=transport)
    client = private or shared_client()
    host = httpx.URL(url).host
    if private is None:
        attempts = _attempts_allowed(host, attempts, url)
    try:
        for attempt in range(attempts):
            if before_attempt is not None:
                before_attempt()
            response = None
            try:
                response = client.get(url, params=params, headers=headers, auth=auth, timeout=request_timeout)
            except httpx.TransportError as exc:
                if attempt + 1 >= attempts:
                    if private is None and isinstance(exc, _CONNECT_FAILURES):
                        with _failed_lock:
                            _failed_at[host] = _clock()
                    raise
            else:
                if private is None and host in _failed_at:
                    with _failed_lock:
                        _failed_at.pop(host, None)
                if response.status_code not in RETRYABLE_STATUS_CODES or attempt + 1 >= attempts:
                    return response
                response.close()

            sleep(_retry_delay(response, attempt))
    finally:
        if private is not None:
            private.close()

    raise RuntimeError("HTTP retry loop ended unexpectedly")


def _attempts_allowed(host: str, attempts: int, url: str) -> int:
    """Attempts for this request: none while the host is paused, one while it recovers."""

    with _failed_lock:
        failed = _failed_at.get(host)
    if failed is None:
        return attempts
    since = _clock() - failed
    if since < UNREACHABLE_PAUSE_SECONDS:
        raise httpx.ConnectError(
            f"{host} could not be reached a moment ago; not trying again for "
            f"{UNREACHABLE_PAUSE_SECONDS - since:.0f} s.",
            request=httpx.Request("GET", url),
        )
    if since < RECOVERY_WINDOW_SECONDS:
        return 1
    return attempts
