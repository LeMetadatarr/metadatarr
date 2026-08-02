"""Disk-backed HTTP cache: round-trip write/read, TTL expiry, GET-only scope.

No network involved — ``requests.Response`` objects are built in-memory and
fed through the module's own read/write helpers, which is the same path
``_patched_send`` uses once ``setup()`` monkey-patches ``requests.Session.send``.
"""
from __future__ import annotations

import time

import pytest
import requests

import metadatarr.resolve._http_cache as http_cache


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Point the module at a scratch directory and reset global state per test."""
    monkeypatch.setattr(http_cache, "_cache_dir", tmp_path)
    monkeypatch.setattr(http_cache, "_ttl", None)
    yield tmp_path


def _response(body: bytes = b"hello world", status: int = 200) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.headers = requests.structures.CaseInsensitiveDict({"Content-Type": "text/plain"})
    r.encoding = "utf-8"
    r.url = "https://example.com/x"
    r._content = body
    r._content_consumed = True
    return r


def test_write_then_read_round_trips_content(tmp_path):
    key = http_cache._cache_key("GET", "https://example.com/x", None)
    path = http_cache._cache_path(key)

    http_cache._write_entry(path, _response(b"payload-bytes"))
    entry = http_cache._read_entry(path)

    assert entry is not None
    rebuilt = http_cache._make_response(entry)
    assert rebuilt.content == b"payload-bytes"
    assert rebuilt.status_code == 200


def test_read_missing_entry_returns_none(tmp_path):
    path = http_cache._cache_path("does-not-exist")
    assert http_cache._read_entry(path) is None


def test_ttl_expiry_deletes_stale_entry(tmp_path, monkeypatch):
    key = http_cache._cache_key("GET", "https://example.com/x", None)
    path = http_cache._cache_path(key)
    http_cache._write_entry(path, _response())

    # Backdate the entry beyond a 1-second TTL.
    monkeypatch.setattr(http_cache, "_ttl", 1)
    entry = http_cache._read_entry(path)
    assert entry is not None  # not yet expired

    stale = {**entry, "ts": time.time() - 10}
    path.write_text(__import__("json").dumps(stale), encoding="utf-8")

    assert http_cache._read_entry(path) is None
    assert not path.exists()  # expired entry is evicted from disk


def test_cache_key_differs_by_method_url_and_body():
    a = http_cache._cache_key("GET", "https://example.com/x", None)
    b = http_cache._cache_key("GET", "https://example.com/y", None)
    c = http_cache._cache_key("POST", "https://example.com/x", None)
    d = http_cache._cache_key("GET", "https://example.com/x", b"body")
    assert len({a, b, c, d}) == 4


def test_patched_send_bypasses_cache_for_non_get_head(monkeypatch, tmp_path):
    calls = []

    def fake_original_send(self, request, **kwargs):
        calls.append(request.method)
        return _response(b"live")

    monkeypatch.setattr(http_cache, "_original_send", fake_original_send)

    req = requests.Request(method="POST", url="https://example.com/x").prepare()
    session = requests.Session()
    result = http_cache._patched_send(session, req)

    assert calls == ["POST"]
    assert result.content == b"live"
    # Nothing was written to the cache dir for a POST request.
    assert list(tmp_path.glob("*.json")) == []


def test_patched_send_caches_get_on_first_call_then_hits(monkeypatch, tmp_path):
    calls = []

    def fake_original_send(self, request, **kwargs):
        calls.append(1)
        return _response(b"fresh")

    monkeypatch.setattr(http_cache, "_original_send", fake_original_send)

    req = requests.Request(method="GET", url="https://example.com/x").prepare()
    session = requests.Session()

    first = http_cache._patched_send(session, req)
    second = http_cache._patched_send(session, req)

    assert first.content == b"fresh"
    assert second.content == b"fresh"
    assert len(calls) == 1  # second call served from disk cache, no network hit
