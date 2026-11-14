"""Provider connections retry only when a failure is likely temporary."""

from __future__ import annotations

import httpx

from vela.network import retrying_get


def test_retrying_get_recovers_from_transient_statuses():
    calls = []
    waits = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, text="ready", request=request)

    response = retrying_get(
        "https://provider.example/data",
        transport=httpx.MockTransport(handler),
        sleep=waits.append,
    )

    assert response.status_code == 200
    assert response.text == "ready"
    assert len(calls) == 3
    assert waits == [0.25, 0.5]


def test_retrying_get_does_not_retry_permanent_client_errors():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, request=request)

    response = retrying_get(
        "https://provider.example/private",
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )

    assert response.status_code == 401
    assert len(calls) == 1


def test_retrying_get_retries_transport_errors_with_a_fixed_limit():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("offline", request=request)

    try:
        retrying_get(
            "https://provider.example/data",
            transport=httpx.MockTransport(handler),
            sleep=lambda _seconds: None,
        )
    except httpx.ConnectError:
        pass
    else:
        raise AssertionError("The final transport error should be raised")

    assert len(calls) == 3
