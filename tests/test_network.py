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


def test_shared_client_is_one_keep_alive_client():
    from vela import network

    assert network.shared_client() is network.shared_client()


def test_requests_reuse_the_shared_client_and_fail_fast_on_connecting(monkeypatch):
    from vela import network

    seen = []

    class FakeClient:
        def get(self, url, **kwargs):
            seen.append((self, kwargs["timeout"]))
            return httpx.Response(200, text="ok", request=httpx.Request("GET", url))

    fake = FakeClient()
    monkeypatch.setattr(network, "shared_client", lambda: fake)

    network.retrying_get("https://provider.example/a", timeout=40.0)
    network.retrying_get("https://provider.example/b", timeout=60.0)

    assert [client for client, _ in seen] == [fake, fake]
    first = seen[0][1]
    # A connection that cannot be made is given up on quickly; a slow answer keeps its allowance.
    assert first.connect == network.CONNECT_TIMEOUT_SECONDS
    assert first.read == 40.0
    assert seen[1][1].read == 60.0


def test_ttl_cache_reuses_fresh_values_and_reloads_expired_ones():
    from vela.network import TtlCache

    now = [0.0]
    loads = []
    cache = TtlCache(clock=lambda: now[0])

    def load():
        loads.append(1)
        return len(loads)

    assert cache.get_or_load("key", 10, load) == 1
    assert cache.get_or_load("key", 10, load) == 1
    now[0] = 11
    assert cache.get_or_load("key", 10, load) == 2


def test_ttl_cache_does_not_keep_rejected_values():
    from vela.network import TtlCache

    loads = []
    cache = TtlCache()

    def load():
        loads.append(1)
        return "failed"

    cache.get_or_load("key", 60, load, keep=lambda value: value != "failed")
    cache.get_or_load("key", 60, load, keep=lambda value: value != "failed")
    assert len(loads) == 2


def test_ttl_cache_runs_one_load_for_simultaneous_callers():
    import threading
    import time

    from vela.network import TtlCache

    loads = []
    cache = TtlCache()
    start = threading.Barrier(4)
    results = []

    def load():
        loads.append(1)
        time.sleep(0.05)
        return "answer"

    def caller():
        start.wait()
        results.append(cache.get_or_load("key", 60, load))

    threads = [threading.Thread(target=caller) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == ["answer"] * 4
    assert len(loads) == 1


def test_ttl_cache_stays_within_its_size():
    from vela.network import TtlCache

    cache = TtlCache(max_items=2)
    for key in ("a", "b", "c"):
        cache.get_or_load(key, 60, lambda: key)
    assert len(cache) <= 2


def _unreachable_client(calls):
    class Unreachable:
        def get(self, url, **_kwargs):
            calls.append(url)
            raise httpx.ConnectTimeout("handshake stalled", request=httpx.Request("GET", url))

    return Unreachable()


def test_an_unreachable_host_is_skipped_for_a_while_without_touching_others(monkeypatch):
    from vela import network

    now = [1000.0]
    calls = []
    monkeypatch.setattr(network, "_clock", lambda: now[0])
    monkeypatch.setattr(network, "_failed_at", {})
    monkeypatch.setattr(network, "shared_client", lambda: _unreachable_client(calls))
    quiet = {"sleep": lambda _seconds: None}

    try:
        network.retrying_get("https://weather.example/a", **quiet)
    except httpx.ConnectTimeout:
        pass
    assert len(calls) == 3

    # Within the pause, the host is not contacted at all and the failure is immediate.
    try:
        network.retrying_get("https://weather.example/b", **quiet)
    except httpx.ConnectError as exc:
        assert "weather.example" in str(exc)
    else:
        raise AssertionError("expected an immediate failure")
    assert len(calls) == 3

    # Other providers are unaffected.
    try:
        network.retrying_get("https://satellite.example/c", **quiet)
    except httpx.ConnectTimeout:
        pass
    assert len(calls) == 6


def test_after_the_pause_one_attempt_checks_whether_the_host_is_back(monkeypatch):
    from vela import network

    now = [1000.0]
    calls = []
    monkeypatch.setattr(network, "_clock", lambda: now[0])
    monkeypatch.setattr(network, "_failed_at", {"weather.example": 1000.0})
    monkeypatch.setattr(network, "shared_client", lambda: _unreachable_client(calls))

    now[0] += network.UNREACHABLE_PAUSE_SECONDS + 1
    try:
        network.retrying_get("https://weather.example/a", sleep=lambda _seconds: None)
    except httpx.ConnectTimeout:
        pass
    # Still down: one try, not three, then paused again.
    assert len(calls) == 1
    assert network._failed_at["weather.example"] == now[0]

    class Healthy:
        def get(self, url, **_kwargs):
            calls.append(url)
            return httpx.Response(200, text="ok", request=httpx.Request("GET", url))

    monkeypatch.setattr(network, "shared_client", lambda: Healthy())
    now[0] += network.UNREACHABLE_PAUSE_SECONDS + 1
    assert network.retrying_get("https://weather.example/b", sleep=lambda _s: None).status_code == 200
    assert "weather.example" not in network._failed_at


def test_a_slow_answer_does_not_pause_the_host(monkeypatch):
    from vela import network

    calls = []

    class Slow:
        def get(self, url, **_kwargs):
            calls.append(url)
            raise httpx.ReadTimeout("slow answer", request=httpx.Request("GET", url))

    monkeypatch.setattr(network, "_failed_at", {})
    monkeypatch.setattr(network, "shared_client", lambda: Slow())
    try:
        network.retrying_get("https://busy.example/a", sleep=lambda _s: None)
    except httpx.ReadTimeout:
        pass
    assert network._failed_at == {}
