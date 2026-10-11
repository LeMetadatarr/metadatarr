# SPDX-License-Identifier: Apache-2.0
"""The versioned HTTP API: /api/v1 routes and their unversioned aliases,
batch resolve, video and audio identify, API keys, rate limiting, caching
headers and cache bypass. Offline: providers are stubs registered here."""
from __future__ import annotations

import asyncio
import io
import os
import sys
import threading
from types import ModuleType
from typing import Optional
from unittest import mock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from mediavocab import MediaType  # noqa: E402
from mediavocab.models import ExternalIds  # noqa: E402
from mediavocab.models.signals import Signals  # noqa: E402

from metadatarr.resolve import base as resolve_base  # noqa: E402
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register  # noqa: E402
from metadatarr.server.app import create_app  # noqa: E402
from metadatarr.server.config import ServerConfig, parse_networks  # noqa: E402
from metadatarr.server.security import TokenBucket  # noqa: E402
from metadatarr.transport import cache_bypassed  # noqa: E402
from metadatarr.version import __version__  # noqa: E402

PREFIX = "zzv1"  # titles this module's provider answers; every other provider ignores them


class _CountingProvider(MetadataProvider):
    name = "zz_v1_counting"
    media = {MediaType.MOVIE, MediaType.EPISODIC_SERIES}

    def __init__(self):
        self.calls = []
        self.bypass_seen = []

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not (signals.title or "").lower().startswith(PREFIX):
            return None
        self.calls.append(signals.title)
        self.bypass_seen.append(cache_bypassed())
        if "boom" in signals.title:
            raise RuntimeError("provider exploded")
        return ProviderMatch(
            provider=self.name,
            confidence=0.9,
            signals=Signals(title=signals.title, year=signals.year, medium=signals.medium),
            external_ids=ExternalIds(tmdb_movie=1000 + len(signals.title)),
        )


@pytest.fixture()
def provider():
    p = _CountingProvider()
    register(p)
    yield p
    resolve_base._REGISTRY.pop(p.name, None)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for var in ("METADATARR_API_KEYS", "METADATARR_AUTH_EXEMPT", "METADATARR_RATE_LIMIT",
                "METADATARR_RATE_LIMIT_BURST", "METADATARR_AUDIO_ROOTS",
                "METADATARR_MAX_UPLOAD_BYTES", "METADATARR_HTTP_CACHE",
                "METADATARR_HTTP_CACHE_TTL"):
        monkeypatch.delenv(var, raising=False)
    from metadatarr.resolve._cache import cache
    cache().clear()
    yield
    cache().clear()


def _client(config: Optional[ServerConfig] = None, **kwargs) -> TestClient:
    return TestClient(create_app(config or ServerConfig()), **kwargs)


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

def test_openapi_version_is_package_version():
    schema = _client().get("/openapi.json").json()
    assert schema["info"]["version"] == __version__


@pytest.mark.parametrize("path", ["/healthz", "/stats", "/providers"])
def test_get_routes_served_versioned_and_unversioned(path):
    client = _client()
    assert client.get("/api/v1" + path).status_code == 200
    assert client.get(path).status_code == 200


def test_post_routes_served_versioned_and_unversioned(provider):
    client = _client()
    for path in ("/resolve", "/candidates"):
        for prefix in ("/api/v1", ""):
            resp = client.post(prefix + path, json={"title": f"{PREFIX} alias", "medium": "movie"})
            assert resp.status_code == 200, (prefix + path, resp.text)
    for prefix in ("/api/v1", ""):
        assert client.post(prefix + "/enrich", json={}).status_code == 200


def test_schema_lists_versioned_paths_only():
    paths = _client().get("/openapi.json").json()["paths"]
    for p in ("/api/v1/resolve", "/api/v1/resolve/batch", "/api/v1/identify/video",
              "/api/v1/identify/audio", "/api/v1/healthz"):
        assert p in paths
    assert "/resolve" not in paths and "/healthz" not in paths


# ---------------------------------------------------------------------------
# Batch resolve
# ---------------------------------------------------------------------------

def test_batch_returns_results_in_request_order(provider):
    titles = [f"{PREFIX} item {i:02d}" for i in range(20)]
    resp = _client().post("/api/v1/resolve/batch", json={
        "items": [{"title": t, "medium": "movie"} for t in titles]})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert [r["index"] for r in results] == list(range(20))
    assert all(r["ok"] for r in results)
    assert [r["result"]["signals"]["title"] for r in results] == titles


def test_batch_invalid_item_fails_alone(provider):
    resp = _client().post("/api/v1/resolve/batch", json={"items": [
        {"title": f"{PREFIX} good", "medium": "movie"},
        {"title": f"{PREFIX} bad", "medium": "not-a-medium"},
        {"nonsense_field": 1},
    ]})
    assert resp.status_code == 200
    r = resp.json()["results"]
    assert r[0]["ok"] is True
    assert r[1]["ok"] is False and "medium" in r[1]["error"]
    assert r[2]["ok"] is False and "nonsense_field" in r[2]["error"]
    assert resp.headers["cache-control"] == "no-cache"


def test_batch_resolve_exception_fails_alone(provider, monkeypatch):
    from metadatarr.server import routes

    real = routes.run_resolve

    def flaky(signals, **kw):
        if signals.title.endswith("explode"):
            raise RuntimeError("secret internal detail")
        return real(signals, **kw)

    monkeypatch.setattr(routes, "run_resolve", flaky)
    resp = _client().post("/api/v1/resolve/batch", json={"items": [
        {"title": f"{PREFIX} explode", "medium": "movie"},
        {"title": f"{PREFIX} fine", "medium": "movie"},
    ]})
    r = resp.json()["results"]
    assert r[0]["ok"] is False and r[0]["error"] == "RuntimeError: resolve failed"
    assert r[1]["ok"] is True


@pytest.mark.parametrize("n", [0, 101])
def test_batch_size_bounds(n):
    resp = _client().post("/api/v1/resolve/batch", json={"items": [{"title": "x"}] * n})
    assert resp.status_code == 422


def test_batch_of_100_accepted(provider):
    resp = _client().post("/api/v1/resolve/batch", json={
        "items": [{"title": f"{PREFIX} {i}", "medium": "movie"} for i in range(100)]})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 100


# ---------------------------------------------------------------------------
# Video identify
# ---------------------------------------------------------------------------

def test_identify_video_parses_name_and_resolves(provider):
    resp = _client().post("/api/v1/identify/video", json={
        "filename": f"/srv/movies/{PREFIX}.Movie.2010.1080p.BluRay.x264.mkv",
        "duration": 8880.5, "size": 123456})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == f"{PREFIX}.Movie.2010.1080p.BluRay.x264.mkv"
    assert body["signals"]["year"] == 2010
    assert body["signals"]["medium"] == "movie"
    assert body["signals"]["runtime"] == 8880.5
    assert body["signals"]["title"].lower().startswith(PREFIX)
    assert provider.calls, "resolve never reached the provider"
    assert body["result"]["external_ids"]["tmdb_movie"]


def test_identify_video_hints_override_and_episode_parse(provider):
    resp = _client().post("/api/v1/identify/video", json={
        "filename": f"C:\\TV\\{PREFIX} Show S02E05 720p.mkv",
        "hints": {"year": 1999, "country": "US"}})
    body = resp.json()
    assert body["filename"] == f"{PREFIX} Show S02E05 720p.mkv"
    assert body["signals"]["season"] == 2 and body["signals"]["episode"] == 5
    assert body["signals"]["year"] == 1999 and body["signals"]["country"] == "US"


def test_identify_video_reports_embedded_ids(provider):
    body = _client().post("/api/v1/identify/video", json={
        "filename": f"{PREFIX} Film (2001) {{tmdb-4242}}.mkv"}).json()
    assert body["embedded_ids"]["tmdb_movie"] == 4242


def test_identify_video_never_opens_the_file(provider, monkeypatch, tmp_path):
    from metadatarr import library

    def forbidden(*a, **kw):
        raise AssertionError("server must not probe a client-supplied name")

    monkeypatch.setattr(library, "_ffprobe_tags", forbidden)
    monkeypatch.setattr(library, "_mutagen_music_signals", forbidden)
    real = tmp_path / f"{PREFIX}.Film.2003.mkv"
    real.write_bytes(b"not a video")
    monkeypatch.chdir(tmp_path)
    resp = _client().post("/api/v1/identify/video", json={"filename": real.name})
    assert resp.status_code == 200


@pytest.mark.parametrize("payload", [
    {"filename": ""},
    {"filename": "/srv/movies/"},
    {"filename": "x.mkv", "hints": {"bogus": 1}},
    {"filename": "x.mkv", "hints": {"medium": "not-a-medium"}},
    {"filename": "x.mkv", "duration": -5},
])
def test_identify_video_rejects_bad_input(payload):
    assert _client().post("/api/v1/identify/video", json=payload).status_code == 422


# ---------------------------------------------------------------------------
# Audio identify: uploads, and paths only inside allowed roots
# ---------------------------------------------------------------------------

class _FakeTrack:
    key = "1"
    title = "Song"
    subtitle = "Artist"
    url = "https://shazam.example/1"
    cover_art = ""
    apple_music_url = ""
    spotify_uri = ""
    deezer_uri = ""
    metadata_table = {}


class _FakeResult:
    matched = True
    track = _FakeTrack()


@pytest.fixture()
def fake_xazam():
    seen = []

    class _Client:
        def __init__(self, transport):
            pass

        async def identify(self, audio):
            seen.append(audio)
            return _FakeResult()

    class _Transport:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    mod = ModuleType("xazam")
    mod.ShazamClient = _Client
    mod.ShazamTransport = _Transport
    with mock.patch.dict(sys.modules, {"xazam": mod}), \
         mock.patch("metadatarr.identify.run_resolve",
                    return_value=resolve_base.ResolveResult(signals=None)), \
         mock.patch("metadatarr.identify.run_enrich", return_value=ExternalIds()):
        yield seen


@pytest.fixture()
def audio_tree(tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    (root / "track.mp3").write_bytes(b"inside")
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"outside")
    (root / "escape.mp3").symlink_to(outside)
    sibling = tmp_path / "music-evil"
    sibling.mkdir()
    (sibling / "x.mp3").write_bytes(b"sibling")
    return root, outside, sibling


def test_identify_audio_path_inside_root_is_read(fake_xazam, audio_tree):
    root, _, _ = audio_tree
    client = _client(ServerConfig(audio_roots=[str(root)]))
    resp = client.post("/api/v1/identify/audio", params={"path": str(root / "track.mp3")})
    assert resp.status_code == 200, resp.text
    assert fake_xazam == [b"inside"]


@pytest.mark.parametrize("make_path", [
    lambda root, outside, sibling: str(outside),
    lambda root, outside, sibling: str(root / ".." / outside.name),
    lambda root, outside, sibling: str(root / "escape.mp3"),
    lambda root, outside, sibling: str(sibling / "x.mp3"),
    lambda root, outside, sibling: "/etc/passwd",
    lambda root, outside, sibling: str(root),
    lambda root, outside, sibling: str(root / "missing.mp3"),
], ids=["absolute", "dotdot", "symlink", "sibling-prefix", "system-file", "root-dir", "missing"])
def test_identify_audio_path_outside_root_is_refused(fake_xazam, audio_tree, make_path):
    root, outside, sibling = audio_tree
    client = _client(ServerConfig(audio_roots=[str(root)]))
    for prefix in ("/api/v1", ""):
        resp = client.post(prefix + "/identify/audio",
                           params={"path": make_path(root, outside, sibling)})
        assert resp.status_code == 403, resp.text
    assert fake_xazam == [], "a refused path was read"


def test_identify_audio_path_refused_without_roots(fake_xazam, audio_tree):
    root, outside, _ = audio_tree
    resp = _client().post("/identify/audio", params={"path": str(outside)})
    assert resp.status_code == 403
    assert fake_xazam == []


def test_identify_audio_upload_size_limit(fake_xazam):
    client = _client(ServerConfig(max_upload_bytes=10))
    ok = client.post("/api/v1/identify/audio",
                     files={"file": ("a.mp3", io.BytesIO(b"0123456789"), "audio/mpeg")})
    assert ok.status_code == 200
    big = client.post("/api/v1/identify/audio",
                      files={"file": ("a.mp3", io.BytesIO(b"0123456789X"), "audio/mpeg")})
    assert big.status_code == 413
    assert fake_xazam == [b"0123456789"]


def test_identify_audio_runs_provider_work_off_the_event_loop(fake_xazam):
    from metadatarr.identify import identify_audio_async

    threads = {}

    def record(name):
        def _f(*a, **kw):
            threads[name] = threading.get_ident()
            return (resolve_base.ResolveResult(signals=None) if name == "resolve"
                    else ExternalIds())
        return _f

    async def run():
        threads["loop"] = threading.get_ident()
        return await identify_audio_async(b"bytes")

    with mock.patch("metadatarr.identify.run_resolve", side_effect=record("resolve")), \
         mock.patch("metadatarr.identify.run_enrich", side_effect=record("enrich")):
        asyncio.run(run())
    assert threads["resolve"] != threads["loop"]
    assert threads["enrich"] != threads["loop"]


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

def test_auth_off_by_default(provider):
    assert ServerConfig.from_env({}).auth_enabled is False
    assert _client().post("/api/v1/resolve", json={"title": f"{PREFIX} open"}).status_code == 200


def test_auth_requires_a_valid_key(provider):
    client = _client(ServerConfig(api_keys=["k1", "k2"]))
    body = {"title": f"{PREFIX} auth", "medium": "movie"}
    assert client.post("/api/v1/resolve", json=body).status_code == 401
    assert client.post("/resolve", json=body).status_code == 401
    assert client.post("/api/v1/resolve", json=body,
                       headers={"X-Api-Key": "wrong"}).status_code == 401
    assert client.post("/api/v1/resolve", json=body,
                       headers={"X-Api-Key": "k2"}).status_code == 200
    assert client.post("/api/v1/resolve?apikey=k1", json=body).status_code == 200
    assert client.get("/ui/providers").status_code == 401


def test_auth_leaves_health_and_static_open():
    client = _client(ServerConfig(api_keys=["k"]))
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/healthz").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_exempt_network_needs_no_key(provider):
    config = ServerConfig(api_keys=["k"], exempt_networks=parse_networks("private"))
    lan = _client(config, client=("192.168.1.50", 5000))
    assert lan.post("/api/v1/resolve", json={"title": f"{PREFIX} lan"}).status_code == 200
    mapped = _client(config, client=("::ffff:10.1.2.3", 5000))
    assert mapped.get("/api/v1/stats").status_code == 200
    wan = _client(config, client=("203.0.113.9", 5000))
    assert wan.post("/api/v1/resolve", json={"title": f"{PREFIX} wan"}).status_code == 401


def test_config_from_env():
    cfg = ServerConfig.from_env({
        "METADATARR_API_KEYS": " a, b ,,",
        "METADATARR_AUTH_EXEMPT": "10.0.0.0/8, 192.168.1.7",
        "METADATARR_RATE_LIMIT": "30",
        "METADATARR_AUDIO_ROOTS": os.pathsep.join(["/m1", "/m2"]),
        "METADATARR_MAX_UPLOAD_BYTES": "99",
    })
    assert cfg.api_keys == ["a", "b"]
    assert [str(n) for n in cfg.exempt_networks] == ["10.0.0.0/8", "192.168.1.7/32"]
    assert cfg.rate_limit_per_minute == 30 and cfg.burst == 30
    assert cfg.audio_roots == ["/m1", "/m2"]
    assert cfg.max_upload_bytes == 99
    with pytest.raises(ValueError):
        parse_networks("not-a-network")


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def test_token_bucket_refills_over_time():
    now = [0.0]
    bucket = TokenBucket(rate=1.0, burst=2, time_func=lambda: now[0])
    assert bucket.take("a") == 0 and bucket.take("a") == 0
    assert bucket.take("a") == pytest.approx(1.0)
    assert bucket.take("b") == 0, "buckets are per key"
    now[0] = 0.5
    assert bucket.take("a") == pytest.approx(0.5)
    now[0] = 1.0
    assert bucket.take("a") == 0


def test_token_bucket_prunes_idle_full_buckets():
    now = [0.0]
    bucket = TokenBucket(rate=1.0, burst=1, time_func=lambda: now[0])
    bucket._PRUNE_AT = 3
    for k in "abcd":
        bucket.take(k)
    now[0] = 5.0
    bucket.take("e")
    assert set(bucket._state) == {"e"}


def test_rate_limit_answers_429_with_retry_after():
    client = _client(ServerConfig(api_keys=["k1", "k2"], rate_limit_per_minute=6,
                                  rate_limit_burst=2))
    h1 = {"X-Api-Key": "k1"}
    assert client.get("/api/v1/stats", headers=h1).status_code == 200
    assert client.get("/api/v1/stats", headers=h1).status_code == 200
    limited = client.get("/api/v1/stats", headers=h1)
    assert limited.status_code == 429
    assert 1 <= int(limited.headers["Retry-After"]) <= 10
    assert client.get("/api/v1/stats", headers={"X-Api-Key": "k2"}).status_code == 200
    assert client.get("/healthz", headers=h1).status_code == 200


def test_rate_limit_without_auth_is_per_client_address():
    config = ServerConfig(rate_limit_per_minute=60, rate_limit_burst=1)
    app = create_app(config)
    a = TestClient(app, client=("198.51.100.1", 1))
    b = TestClient(app, client=("198.51.100.2", 1))
    assert a.get("/api/v1/stats").status_code == 200
    assert a.get("/api/v1/stats").status_code == 429
    assert b.get("/api/v1/stats").status_code == 200


# ---------------------------------------------------------------------------
# Caching headers and ?refresh=1
# ---------------------------------------------------------------------------

def test_cache_headers_follow_provider_cache_ttl(provider, monkeypatch):
    monkeypatch.setenv("METADATARR_HTTP_CACHE_TTL", "1234")
    resp = _client().post("/api/v1/resolve", json={"title": f"{PREFIX} ttl", "medium": "movie"})
    assert resp.headers["cache-control"] == "public, max-age=1234"
    assert resp.headers["etag"].startswith('"')


def test_cache_headers_private_when_auth_enabled(provider):
    client = _client(ServerConfig(api_keys=["k"]))
    resp = client.post("/api/v1/resolve", json={"title": f"{PREFIX} p", "medium": "movie"},
                       headers={"X-Api-Key": "k"})
    assert resp.headers["cache-control"].startswith("private, max-age=")


def test_get_resolve_conditional_request_gets_304(provider):
    client = _client()
    url = f"/api/v1/resolve?title={PREFIX}%20etag&medium=movie&year=2010"
    first = client.get(url)
    assert first.status_code == 200
    assert first.json()["signals"]["year"] == 2010
    etag = first.headers["etag"]
    second = client.get(url, headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.headers["etag"] == etag
    assert second.content == b""
    assert client.get(url, headers={"If-None-Match": '"other"'}).status_code == 200


def test_get_resolve_rejects_unknown_and_invalid_params():
    client = _client()
    assert client.get("/api/v1/resolve?title=x&bogus=1").status_code == 422
    assert client.get("/api/v1/resolve?title=x&medium=nope").status_code == 422
    assert client.get("/api/v1/resolve?title=x&max_workers=0").status_code == 422


def test_degraded_result_is_not_cacheable(provider):
    resp = _client().post("/api/v1/resolve", json={"title": f"{PREFIX} boom", "medium": "movie"})
    assert resp.status_code == 200
    assert resp.json()["provider_errors"]
    assert resp.headers["cache-control"] == "no-cache"


def test_refresh_bypasses_the_provider_cache(provider):
    client = _client()
    body = {"title": f"{PREFIX} refresh", "medium": "movie"}
    client.post("/api/v1/resolve", json=body)
    client.post("/api/v1/resolve", json=body)
    assert len(provider.calls) == 1, "second call should be served from the cache"
    client.post("/api/v1/resolve?refresh=1", json=body)
    assert len(provider.calls) == 2
    assert provider.bypass_seen == [False, True], "bypass must reach the provider thread"
    client.post("/api/v1/resolve", json=body)
    assert len(provider.calls) == 2, "refresh writes the fresh result back"


def test_refresh_on_batch_and_identify_video(provider):
    client = _client()
    item = {"title": f"{PREFIX} rb", "medium": "movie"}
    client.post("/api/v1/resolve/batch", json={"items": [item]})
    client.post("/api/v1/resolve/batch?refresh=1", json={"items": [item]})
    assert provider.bypass_seen == [False, True]
    client.post("/api/v1/identify/video?refresh=1", json={"filename": f"{PREFIX}.Rv.2001.mkv"})
    assert provider.bypass_seen[-1] is True


def test_http_disk_cache_is_bypassed_but_refreshed(tmp_path):
    import requests

    from metadatarr.transport import (
        CachingRateLimitedAdapter, DiskCache, HostRateLimiter, bypass_cache)

    cache = DiskCache(tmp_path, ttl=None)
    adapter = CachingRateLimitedAdapter(HostRateLimiter(), cache)
    sent = []

    def fake_send(self, request, **kwargs):
        sent.append(request.url)
        r = requests.Response()
        r.status_code = 200
        r._content = f"fresh-{len(sent)}".encode()
        r.url = request.url
        return r

    req = requests.Request("GET", "https://example.invalid/x").prepare()
    with mock.patch("requests.adapters.HTTPAdapter.send", fake_send):
        assert adapter.send(req).content == b"fresh-1"
        assert adapter.send(req).content == b"fresh-1"
        with bypass_cache():
            assert adapter.send(req).content == b"fresh-2"
        assert adapter.send(req).content == b"fresh-2"
    assert len(sent) == 2


# ---------------------------------------------------------------------------
# Review fixes: proxy headers, non-finite floats, upload cap, batch cost
# ---------------------------------------------------------------------------

def test_run_ignores_forwarded_for_from_a_loopback_peer(monkeypatch):
    """A forged X-Forwarded-For must not turn a loopback peer into an exempt
    address: run() starts uvicorn with proxy headers off."""
    import socket
    import time

    import httpx
    import uvicorn

    from metadatarr.server import app as app_module

    monkeypatch.setenv("METADATARR_API_KEYS", "secret")
    monkeypatch.setenv("METADATARR_AUTH_EXEMPT", "10.0.0.0/8")
    captured = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: captured.update(app=app, kw=kw))
    app_module.run(host="127.0.0.1", port=0)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    kw = dict(captured["kw"], host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(uvicorn.Config(captured["app"], **kw))
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        r = httpx.get(f"http://127.0.0.1:{port}/api/v1/stats",
                      headers={"X-Forwarded-For": "10.1.2.3"})
        assert r.status_code == 401
    finally:
        server.should_exit = True
        thread.join(10)


def _strict_json(response):
    import json

    def refuse(token):
        raise AssertionError(f"non-standard JSON constant {token}")

    return json.loads(response.text, parse_constant=refuse)


@pytest.mark.parametrize("value", ["inf", "nan", "-inf"])
@pytest.mark.parametrize("path", ["/resolve", "/api/v1/resolve"])
def test_resolve_non_finite_float_serializes_as_null(provider, path, value):
    r = _client().post(path, json={"title": "zzv1 inf", "runtime": value})
    assert r.status_code == 200
    body = _strict_json(r)
    assert body["signals"]["runtime"] is None


def test_batch_non_finite_float_serializes_as_null(provider):
    r = _client().post("/api/v1/resolve/batch",
                       json={"items": [{"title": "zzv1 inf", "runtime": "inf"}]})
    assert r.status_code == 200
    assert _strict_json(r)["results"][0]["result"]["signals"]["runtime"] is None


@pytest.mark.parametrize("value", ["inf", "nan", "Infinity"])
def test_identify_video_rejects_non_finite_duration(provider, value):
    r = _client().post("/api/v1/identify/video",
                       json={"filename": "zzv1 Movie (2010).mkv", "duration": value})
    assert r.status_code == 422


def test_upload_over_cap_refused_by_content_length_before_parsing(fake_xazam):
    client = _client(ServerConfig(max_upload_bytes=1024 * 1024))
    with mock.patch("starlette.requests.Request.form",
                    side_effect=AssertionError("body was parsed")):
        r = client.post("/api/v1/identify/audio", files={
            "file": ("a.mp3", io.BytesIO(b"x" * 3 * 1024 * 1024), "audio/mpeg")})
    assert r.status_code == 413
    assert fake_xazam == []


def test_upload_cap_counts_bytes_when_length_is_unknown(fake_xazam):
    """A chunked body has no Content-Length: the server stops reading at the cap."""
    from metadatarr.server import security

    cap = 1024 * 1024
    app = create_app(ServerConfig(max_upload_bytes=cap))
    boundary = "bnd"
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            'filename="a.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n').encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    chunk = b"x" * 65536
    sent = []
    messages = [head] + [chunk] * 48 + [tail]  # 3 MiB
    sent_bytes = 0
    responses = []

    async def receive():
        nonlocal sent_bytes
        if not messages:
            return {"type": "http.disconnect"}
        part = messages.pop(0)
        sent_bytes += len(part)
        return {"type": "http.request", "body": part, "more_body": bool(messages)}

    async def send(message):
        responses.append(message)

    scope = {"type": "http", "method": "POST", "path": "/api/v1/identify/audio",
             "raw_path": b"/api/v1/identify/audio", "query_string": b"", "root_path": "",
             "scheme": "http", "http_version": "1.1", "server": ("t", 80),
             "client": ("198.51.100.1", 1),
             "headers": [(b"host", b"t"),
                         (b"content-type", f"multipart/form-data; boundary={boundary}".encode())]}
    asyncio.run(app(scope, receive, send))
    start = next(m for m in responses if m["type"] == "http.response.start")
    assert start["status"] == 413
    assert sent_bytes <= cap + security.UPLOAD_OVERHEAD_ALLOWANCE + 65536
    assert fake_xazam == []


def test_upload_cap_applies_to_unversioned_route_only_for_audio(provider):
    client = _client(ServerConfig(max_upload_bytes=10))
    r = client.post("/resolve", json={"title": "zzv1 " + "x" * 5000})
    assert r.status_code == 200


def test_batch_costs_one_token_per_item(provider):
    app = create_app(ServerConfig(rate_limit_per_minute=1, rate_limit_burst=5))
    client = TestClient(app, client=("198.51.100.9", 1))
    items = [{"title": f"zzv1 {i}"} for i in range(3)]
    assert client.post("/api/v1/resolve/batch", json={"items": items}).status_code == 200
    # 5 - 3 = 2 tokens left, a second batch of 3 cannot be covered.
    second = client.post("/api/v1/resolve/batch", json={"items": items})
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1
    assert len(provider.calls) == 3


def test_batch_larger_than_burst_is_refused_with_a_clear_message(provider):
    client = TestClient(create_app(ServerConfig(rate_limit_per_minute=1, rate_limit_burst=2)),
                        client=("198.51.100.9", 1))
    r = client.post("/api/v1/resolve/batch",
                    json={"items": [{"title": f"zzv1 {i}"} for i in range(3)]})
    assert r.status_code == 429
    assert "burst" in r.json()["detail"]
    assert provider.calls == []


def test_batch_unlimited_when_rate_limit_off(provider):
    r = _client().post("/api/v1/resolve/batch",
                       json={"items": [{"title": f"zzv1 {i}"} for i in range(20)]})
    assert r.status_code == 200


def test_batch_from_exempt_network_is_not_charged(provider):
    config = ServerConfig(rate_limit_per_minute=60, rate_limit_burst=1,
                          exempt_networks=parse_networks("198.51.100.0/24"))
    client = TestClient(create_app(config), client=("198.51.100.9", 1))
    r = client.post("/api/v1/resolve/batch",
                    json={"items": [{"title": f"zzv1 {i}"} for i in range(5)]})
    assert r.status_code == 200


def test_batch_error_items_serialize_null_result_and_null_error(provider):
    r = _client().post("/api/v1/resolve/batch",
                       json={"items": [{"title": "zzv1 ok"}, {"year": "nope"}]})
    ok, bad = r.json()["results"]
    assert ok["error"] is None and bad["result"] is None and bad["ok"] is False


def test_head_is_not_a_supported_method(provider):
    assert _client().head("/api/v1/resolve?title=zzv1").status_code == 405


# ---------------------------------------------------------------------------
# Second review: refund on refused batch, embedded uvicorn, Mount, NaN bodies
# ---------------------------------------------------------------------------

class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _fast_batch(monkeypatch):
    from metadatarr.server import routes

    def boom(signals, max_workers=8):
        raise RuntimeError("stub")

    monkeypatch.setattr(routes, "run_resolve", boom)


@pytest.mark.parametrize("size,drain", [(10, 1), (4, 8)])
def test_refused_batch_succeeds_after_exactly_retry_after(monkeypatch, size, drain):
    _fast_batch(monkeypatch)
    clock = _Clock()
    app = create_app(ServerConfig(rate_limit_per_minute=60, rate_limit_burst=10))
    app.state.rate_bucket._time = clock
    client = TestClient(app, client=("198.51.100.9", 1))
    for _ in range(drain):
        assert client.get("/api/v1/stats").status_code == 200
    items = [{"title": f"t{i}"} for i in range(size)]
    refused = client.post("/api/v1/resolve/batch", json={"items": items})
    assert refused.status_code == 429
    clock.now += int(refused.headers["Retry-After"])
    assert client.post("/api/v1/resolve/batch", json={"items": items}).status_code == 200


def _serve(app, **kw):
    import socket
    import time

    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning", **kw))
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    return server, thread, port


@pytest.mark.parametrize("forged", [
    "10.1.2.3", "10.1.2.3:5555", "[::ffff:10.1.2.3]:1", "[::1]:7", "10.1.2.3, 8.8.8.8"])
@pytest.mark.parametrize("header", ["X-Forwarded-For", "X-Real-IP", "Forwarded"])
def test_embedded_default_uvicorn_cannot_be_given_an_exempt_address(forged, header):
    """uvicorn.run(create_app()) with default proxy headers: a forged
    X-Forwarded-For from loopback still needs a key."""
    import httpx

    config = ServerConfig(api_keys=["secret"],
                          exempt_networks=parse_networks("10.0.0.0/8,::1/128,::ffff:10.0.0.0/104"))
    server, thread, port = _serve(create_app(config))
    try:
        value = f"for={forged}" if header == "Forwarded" else forged
        r = httpx.get(f"http://127.0.0.1:{port}/api/v1/stats", headers={header: value})
        assert r.status_code == 401
        ok = httpx.get(f"http://127.0.0.1:{port}/api/v1/stats", headers={"X-Api-Key": "secret"})
        assert ok.status_code == 200
    finally:
        server.should_exit = True
        thread.join(10)


def test_embedded_direct_lan_client_keeps_its_exemption():
    import httpx

    config = ServerConfig(api_keys=["secret"], exempt_networks=parse_networks("127.0.0.0/8"))
    server, thread, port = _serve(create_app(config))
    try:
        assert httpx.get(f"http://127.0.0.1:{port}/api/v1/stats").status_code == 200
    finally:
        server.should_exit = True
        thread.join(10)


@pytest.mark.parametrize("fmt", ["203.0.113.{i}", "203.0.113.{i}:5555", "[::ffff:203.0.113.{i}]:{i}"])
def test_embedded_default_uvicorn_rate_limit_ignores_forged_addresses(fmt):
    import httpx

    server, thread, port = _serve(create_app(ServerConfig(rate_limit_per_minute=1,
                                                          rate_limit_burst=1)))
    try:
        codes = [httpx.get(f"http://127.0.0.1:{port}/api/v1/stats",
                           headers={"X-Forwarded-For": fmt.format(i=i + 1)}).status_code
                 for i in range(3)]
        assert codes[0] == 200 and codes[1:] == [429, 429]
    finally:
        server.should_exit = True
        thread.join(10)


def test_upload_cap_applies_under_a_mount_prefix(fake_xazam):
    from starlette.applications import Starlette
    from starlette.routing import Mount

    cap = 1024 * 1024
    outer = Starlette(routes=[Mount("/md", app=create_app(ServerConfig(max_upload_bytes=cap)))])
    boundary = "bnd"
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            'filename="a.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n').encode()
    messages = [head] + [b"x" * 65536] * 48 + [f"\r\n--{boundary}--\r\n".encode()]
    state = {"bytes": 0}
    responses = []

    async def receive():
        if not messages:
            return {"type": "http.disconnect"}
        part = messages.pop(0)
        state["bytes"] += len(part)
        return {"type": "http.request", "body": part, "more_body": bool(messages)}

    async def send(message):
        responses.append(message)

    scope = {"type": "http", "method": "POST", "path": "/md/api/v1/identify/audio",
             "raw_path": b"/md/api/v1/identify/audio", "query_string": b"", "root_path": "",
             "scheme": "http", "http_version": "1.1", "server": ("t", 80),
             "client": ("198.51.100.1", 1),
             "headers": [(b"host", b"t"),
                         (b"content-type", f"multipart/form-data; boundary={boundary}".encode())]}
    asyncio.run(outer(scope, receive, send))
    assert next(m for m in responses if m["type"] == "http.response.start")["status"] == 413
    assert state["bytes"] <= cap + 64 * 1024 + 65536
    assert fake_xazam == []


@pytest.mark.parametrize("body", [
    '{"filename": "a.mkv", "duration": NaN}',
    '{"filename": "a.mkv", "duration": Infinity}',
    '{"filename": "a.mkv", "duration": 1e400}',
])
def test_identify_video_non_finite_json_literal_is_422(body):
    r = _client().post("/api/v1/identify/video", content=body,
                       headers={"content-type": "application/json"})
    assert r.status_code == 422
    _strict_json(r)


def test_resolve_nan_year_literal_is_422():
    r = _client().post("/resolve", content='{"title": "x", "year": NaN}',
                       headers={"content-type": "application/json"})
    assert r.status_code == 422
    _strict_json(r)


def test_refused_oversized_batches_are_not_free(monkeypatch):
    _fast_batch(monkeypatch)
    clock = _Clock()
    app = create_app(ServerConfig(rate_limit_per_minute=60, rate_limit_burst=2))
    app.state.rate_bucket._time = clock
    client = TestClient(app, client=("198.51.100.9", 1))
    items = [{"title": f"t{i}"} for i in range(3)]
    codes = [client.post("/api/v1/resolve/batch", json={"items": items}).status_code
             for _ in range(1000)]
    assert codes[:2] == [429, 429]
    last = client.post("/api/v1/resolve/batch", json={"items": items})
    assert last.status_code == 429 and last.json()["detail"] == "rate limit exceeded"
    assert "Retry-After" in last.headers


def test_refused_coverable_batches_are_not_free(monkeypatch):
    _fast_batch(monkeypatch)
    clock = _Clock()
    app = create_app(ServerConfig(rate_limit_per_minute=60, rate_limit_burst=10))
    app.state.rate_bucket._time = clock
    client = TestClient(app, client=("198.51.100.9", 1))
    for _ in range(5):
        assert client.get("/api/v1/stats").status_code == 200  # 5 tokens left
    items = [{"title": f"t{i}"} for i in range(8)]
    first = client.post("/api/v1/resolve/batch", json={"items": items})
    assert first.status_code == 429
    # 8 needed, 4 held after the refused attempt (its own token stays spent).
    assert int(first.headers["Retry-After"]) == 4
    for _ in range(10):
        client.post("/api/v1/resolve/batch", json={"items": items})
    assert client.get("/api/v1/stats").status_code == 429
