"""Small, bounded retry helper for Vela's read-only provider requests."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


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
    """GET with TLS verification and bounded retries for transient failures."""

    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        transport=transport,
    ) as client:
        for attempt in range(attempts):
            if before_attempt is not None:
                before_attempt()
            response = None
            try:
                response = client.get(url, params=params, headers=headers, auth=auth)
            except httpx.TransportError:
                if attempt + 1 >= attempts:
                    raise
            else:
                if response.status_code not in RETRYABLE_STATUS_CODES or attempt + 1 >= attempts:
                    return response
                response.close()

            sleep(_retry_delay(response, attempt))

    raise RuntimeError("HTTP retry loop ended unexpectedly")
