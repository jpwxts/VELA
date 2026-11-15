from concurrent.futures import ThreadPoolExecutor
import httpx
from vela import preparedness


def test_weather_cache_deduplicates_success_and_never_caches_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(preparedness, 'WRITABLE_DATA_DIR', tmp_path)
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200 if url.endswith('good') else 503, content=b'weather')
    monkeypatch.setattr(preparedness, 'retrying_get', get)
    with ThreadPoolExecutor(max_workers=5) as pool:
        values = list(pool.map(lambda _: preparedness.request_bytes('https://example.test/good'), range(5)))
    assert values == [(200, b'weather')] * 5
    assert len(calls) == 1
    for _ in range(2):
        assert preparedness.request_bytes('https://example.test/bad')[0] == 503
    assert len(calls) == 3
