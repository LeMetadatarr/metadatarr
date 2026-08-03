"""Transport layer: per-host rate limiting + disk-cache adapter."""
import threading
from typing import List

import pytest
import requests

from metadatarr import transport
from metadatarr.transport import (
    CachingRateLimitedAdapter,
    DiskCache,
    HostRateLimiter,
    make_session,
)


# ---------------------------------------------------------------------------
# Fake clock — a shared monotonic counter that advances only when a thread
# "sleeps", so spacing is asserted deterministically with no real waiting.
# ---------------------------------------------------------------------------

class FakeClock:
    def __init__(self) -> None:
        self._t = 0.0
        self._lock = threading.Lock()

    def time(self) -> float:
        with self._lock:
            return self._t

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self._t += seconds


def test_limiter_spacing_serialises_same_host():
    clock = FakeClock()
    limiter = HostRateLimiter(per_host={"h": 1.0},
                              time_func=clock.time, sleep_func=clock.sleep)
    # First call is free; each subsequent call advances the clock by one interval.
    limiter.wait("h")
    assert clock.time() == 0.0
    limiter.wait("h")
    assert clock.time() == pytest.approx(1.0)
    limiter.wait("h")
    assert clock.time() == pytest.approx(2.0)


def test_limiter_per_host_independence():
    clock = FakeClock()
    limiter = HostRateLimiter(per_host={"a": 1.0, "b": 1.0},
                              time_func=clock.time, sleep_func=clock.sleep)
    limiter.wait("a")
    limiter.wait("b")  # different host — no forced wait
    assert clock.time() == 0.0


def test_limiter_unlisted_host_no_wait():
    clock = FakeClock()
    limiter = HostRateLimiter(default_interval=0.0,
                              time_func=clock.time, sleep_func=clock.sleep)
    for _ in range(5):
        limiter.wait("unlisted.example")
    assert clock.time() == 0.0


def test_limiter_two_threads_observe_interval():
    clock = FakeClock()
    limiter = HostRateLimiter(per_host={"h": 1.0},
                              time_func=clock.time, sleep_func=clock.sleep)
    limiter.wait("h")  # consume the free first slot

    start = threading.Barrier(2)
    reserved: List[float] = []
    lock = threading.Lock()

    def worker():
        start.wait()
        before = clock.time()
        limiter.wait("h")
        after = clock.time()
        with lock:
            reserved.append(after - before)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Both threads had to wait; their combined advance covers two intervals.
    assert sum(reserved) >= 1.0
    assert clock.time() >= 2.0


# ---------------------------------------------------------------------------
# Adapter cache behaviour — the underlying network send is mocked so no real
# request leaves the process.
# ---------------------------------------------------------------------------

def _fake_response(url: str, status: int = 200, body: bytes = b"payload") -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.url = url
    r._content = body
    r._content_consumed = True
    r.encoding = "utf-8"
    return r


def test_adapter_cache_hit_one_real_send(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_send(self, request, **kwargs):
        calls["n"] += 1
        return _fake_response(request.url)

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)

    cache = DiskCache(tmp_path, ttl=None)
    limiter = HostRateLimiter()
    adapter = CachingRateLimitedAdapter(limiter, cache)

    req = requests.Request("GET", "https://example.com/x").prepare()
    first = adapter.send(req)
    second = adapter.send(req)

    assert first.content == b"payload"
    assert second.content == b"payload"
    assert calls["n"] == 1  # second GET served from disk cache


def test_adapter_ttl_expiry(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_send(self, request, **kwargs):
        calls["n"] += 1
        return _fake_response(request.url)

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)

    cache = DiskCache(tmp_path, ttl=100)
    adapter = CachingRateLimitedAdapter(HostRateLimiter(), cache)
    req = requests.Request("GET", "https://example.com/x").prepare()

    now = [1000.0]
    monkeypatch.setattr(transport.time, "time", lambda: now[0])
    adapter.send(req)          # writes entry at t=1000
    now[0] = 2000.0            # advance well past ttl
    adapter.send(req)          # entry stale → real send again
    assert calls["n"] == 2


def test_adapter_post_not_cached(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_send(self, request, **kwargs):
        calls["n"] += 1
        return _fake_response(request.url)

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)

    cache = DiskCache(tmp_path, ttl=None)
    adapter = CachingRateLimitedAdapter(HostRateLimiter(), cache)
    req = requests.Request("POST", "https://example.com/x", data=b"z").prepare()

    adapter.send(req)
    adapter.send(req)
    assert calls["n"] == 2
    assert not list(tmp_path.glob("*.json"))


def test_env_off_passthrough(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_send(self, request, **kwargs):
        calls["n"] += 1
        return _fake_response(request.url)

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    monkeypatch.delenv("METADATARR_HTTP_CACHE", raising=False)

    session = make_session()
    adapter = session.get_adapter("https://example.com")
    assert isinstance(adapter, CachingRateLimitedAdapter)
    assert adapter._cache is None

    req = requests.Request("GET", "https://example.com/x").prepare()
    adapter.send(req)
    adapter.send(req)
    assert calls["n"] == 2  # no caching, every GET reaches the network


def test_env_on_reads_precommitted_cache(tmp_path, monkeypatch):
    """A cache dir written by the disk-cache format is read back correctly."""
    monkeypatch.setenv("METADATARR_HTTP_CACHE", str(tmp_path))
    monkeypatch.delenv("METADATARR_HTTP_CACHE_TTL", raising=False)

    # Seed one entry through the public store path, then confirm a cold adapter
    # (whose network send would raise) serves it from disk.
    seed = DiskCache(tmp_path, ttl=None)
    seed.store("GET", "https://seeded.example/x", None,
               _fake_response("https://seeded.example/x", body=b"from-disk"))

    def boom(self, request, **kwargs):
        raise AssertionError("network should not be hit on a cache hit")

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", boom)

    session = make_session()
    adapter = session.get_adapter("https://seeded.example")
    req = requests.Request("GET", "https://seeded.example/x").prepare()
    resp = adapter.send(req)
    assert resp.content == b"from-disk"


def test_deprecated_setup_warns(monkeypatch, caplog):
    from metadatarr.resolve import _http_cache

    monkeypatch.delenv("METADATARR_HTTP_CACHE", raising=False)
    with caplog.at_level("WARNING"):
        result = _http_cache.setup()
    assert result is False
    assert any("deprecated" in rec.message for rec in caplog.records)
