# SPDX-License-Identifier: Apache-2.0
"""HTTP server smoke tests — JSON API + WebUI.

The deterministic tests never hit real provider networks: `/resolve` and
`/candidates` are exercised against a monkeypatched provider registry so the
suite is fast and reproducible. A separate, explicitly network-marked test
hits the real resolver against live providers and can be skipped without a
network connection.
"""
from __future__ import annotations

import os
from typing import Optional

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register  # noqa: E402
from metadatarr.server.app import create_app  # noqa: E402
from metadatarr.version import __version__  # noqa: E402
from mediavocab import MediaType  # noqa: E402
from mediavocab.models import ExternalIds  # noqa: E402
from mediavocab.models.signals import Signals  # noqa: E402


class _StubMovieProvider(MetadataProvider):
    name = "stub_movie_test"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return ProviderMatch(
            provider=self.name,
            confidence=0.9,
            signals=Signals(title=signals.title, year=signals.year, medium=MediaType.MOVIE),
            external_ids=ExternalIds(tmdb_movie=27205),
        )


@pytest.fixture(scope="module", autouse=True)
def _register_stub_provider():
    register(_StubMovieProvider())
    yield


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_providers(client):
    resp = client.get("/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] > 0
    assert "providers" in body
    names = [p["name"] for p in body["providers"]]
    assert "stub_movie_test" in names
    for p in body["providers"]:
        assert set(p.keys()) == {"name", "available", "media", "modality", "genre_filter"}


def test_resolve_uses_stub_provider(client):
    resp = client.post("/resolve", json={"title": "Inception", "year": 2010, "medium": "movie"})
    assert resp.status_code == 200
    body = resp.json()
    assert "external_ids" in body
    assert "accepted" in body
    assert body["external_ids"]["tmdb_movie"] == 27205
    assert any(m["provider"] == "stub_movie_test" for m in body["accepted"])


def test_candidates_ranked(client):
    resp = client.post("/candidates", json={"title": "Inception", "year": 2010, "medium": "movie"})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(m["provider"] == "stub_movie_test" for m in body)


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "metadatarr" in resp.text


def test_ui_providers_page(client):
    resp = client.get("/ui/providers")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_ui_mappings_page(client):
    resp = client.get("/ui/mappings")
    assert resp.status_code == 200


def test_static_app_css(client):
    resp = client.get("/static/app.css")
    assert resp.status_code == 200
    assert "--accent" in resp.text


def test_static_htmx_vendored(client):
    resp = client.get("/static/htmx.min.js")
    assert resp.status_code == 200
    assert len(resp.text) > 1000


def test_enrich_bogus_medium_returns_client_error(client):
    """A malformed `medium` must not crash the app with an uncaught ValueError."""
    resp = client.post("/enrich", json={"external_ids": {}, "medium": "bogus"})
    assert resp.status_code in (400, 422)


def test_ui_resolve_bogus_medium_does_not_500(client):
    """A malformed `medium` submitted via the resolve form must be handled gracefully."""
    resp = client.post("/ui/resolve", data={"title": "Inception", "medium": "bogus"})
    assert resp.status_code != 500
    assert resp.status_code in (200, 422)


def test_ui_resolve_surfaces_provider_errors(client, monkeypatch):
    """provider_errors from consolidate() must reach the rendered fragment, not be wiped."""
    from metadatarr.server import web as web_mod

    class _FakeResult:
        signals = None
        accepted = []
        dropped = []
        conflicts = []
        external_ids = None
        provider_errors = ["stub_movie_test: boom"]

    monkeypatch.setattr(web_mod, "consolidate", lambda matches, signals: _FakeResult())

    resp = client.post("/ui/resolve", data={"title": "Inception", "medium": "movie"})
    assert resp.status_code == 200
    assert "boom" in resp.text


@pytest.mark.skipif(
    os.environ.get("METADATARR_SKIP_NETWORK_TESTS", "1") == "1",
    reason="live network test — set METADATARR_SKIP_NETWORK_TESTS=0 to run",
)
def test_resolve_live_network(client):
    """Loose live-network smoke test: real providers, no exact-id assertions."""
    resp = client.post("/resolve", json={"title": "Inception", "year": 2010, "medium": "movie"})
    assert resp.status_code == 200
    body = resp.json()
    assert "external_ids" in body
    assert "accepted" in body


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------

def test_stats_counts_resolves_and_scans_cache(tmp_path, monkeypatch):
    cache_dir = tmp_path / "http-cache"
    cache_dir.mkdir()
    (cache_dir / "a.json").write_text("12345")
    (cache_dir / "b.json").write_text("123")
    (cache_dir / "ignored.txt").write_text("not a cache entry")
    monkeypatch.setenv("METADATARR_HTTP_CACHE", str(cache_dir))
    c = TestClient(create_app())

    assert c.get("/stats").json() == {
        "resolves_total": 0, "cache_enabled": True,
        "cache_entries": 2, "cache_bytes": 8}

    for _ in range(2):
        assert c.post("/resolve", json={
            "title": "Inception", "year": 2010, "medium": "movie"}).status_code == 200
    c.post("/candidates", json={"title": "Inception", "medium": "movie"})

    assert c.get("/stats").json()["resolves_total"] == 2


def test_stats_reports_no_cache_when_caching_is_disabled(tmp_path, monkeypatch):
    from metadatarr import transport
    default_dir = tmp_path / "default-cache"
    default_dir.mkdir()
    (default_dir / "stale.json").write_text("12345")
    monkeypatch.setattr(transport, "_DEFAULT_CACHE_DIR", default_dir)
    monkeypatch.delenv("METADATARR_HTTP_CACHE", raising=False)

    body = TestClient(create_app()).get("/stats").json()

    assert body["cache_enabled"] is False
    assert body["cache_entries"] == 0
    assert body["cache_bytes"] == 0


def test_stats_counter_is_per_app(monkeypatch, tmp_path):
    monkeypatch.setenv("METADATARR_HTTP_CACHE", str(tmp_path / "empty"))
    first, second = TestClient(create_app()), TestClient(create_app())
    first.post("/resolve", json={"title": "Inception", "medium": "movie"})
    assert first.get("/stats").json()["resolves_total"] == 1
    assert second.get("/stats").json()["resolves_total"] == 0
    assert second.get("/stats").json()["cache_entries"] == 0


def test_stats_survives_cache_file_vanishing(tmp_path, monkeypatch):
    from pathlib import Path
    cache_dir = tmp_path / "http-cache"
    cache_dir.mkdir()
    (cache_dir / "a.json").write_text("1234")
    (cache_dir / "b.json").write_text("56")
    monkeypatch.setenv("METADATARR_HTTP_CACHE", str(cache_dir))
    real_stat = Path.stat

    def flaky(self, *a, **k):
        if self.name == "b.json":
            raise FileNotFoundError(self)
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", flaky)
    resp = TestClient(create_app()).get("/stats")
    assert resp.status_code == 200
    assert resp.json()["cache_bytes"] == 4
