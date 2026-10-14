# SPDX-License-Identifier: Apache-2.0
"""Additional HTTP server / WebUI coverage — the gaps left by test_server.py.

All deterministic: providers are stubbed so nothing here touches the real
network. Focus areas: /candidates ranking, /resolve conflict/error surfacing,
/enrich round-trips, the /ui/resolve form rendering, /ui/providers content,
/ui/mappings content, /healthz version, and that static assets + package data
actually resolve (guards packaging regressions).
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


class _LowConfidenceProvider(MetadataProvider):
    """A second movie provider that agrees but with lower confidence.

    Used to prove /candidates ranks by confidence, not registration order —
    this provider self-registers *after* the high-confidence one below.
    """

    name = "stub_movie_low"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        return ProviderMatch(
            provider=self.name,
            confidence=0.3,
            signals=Signals(title=signals.title, medium=MediaType.MOVIE),
            external_ids=ExternalIds(imdb="tt0000001"),
        )


class _HighConfidenceProvider(MetadataProvider):
    name = "stub_movie_high"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        return ProviderMatch(
            provider=self.name,
            confidence=0.95,
            signals=Signals(title=signals.title, medium=MediaType.MOVIE),
            external_ids=ExternalIds(imdb="tt9999999"),
        )


class _RaisingProvider(MetadataProvider):
    """A movie provider that always blows up — exercises provider_errors."""

    name = "stub_movie_raises"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        raise RuntimeError("upstream schema drift")


class _ConflictingProvider(MetadataProvider):
    """Agrees on nothing: a different title/year than the input signals."""

    name = "stub_movie_conflict"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        return ProviderMatch(
            provider=self.name,
            confidence=0.6,
            signals=Signals(title="A Completely Different Film", year=1950,
                             medium=MediaType.MOVIE),
            external_ids=ExternalIds(imdb="tt0000002"),
        )


@pytest.fixture(scope="module", autouse=True)
def _register_stub_providers():
    register(_LowConfidenceProvider())
    register(_HighConfidenceProvider())
    register(_RaisingProvider())
    register(_ConflictingProvider())
    yield


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /candidates
# ---------------------------------------------------------------------------

def test_candidates_ranked_by_confidence_descending(client):
    resp = client.post("/candidates", json={"title": "Whatever", "medium": "movie"})
    assert resp.status_code == 200
    body = resp.json()
    names = [m["provider"] for m in body]
    assert names.index("stub_movie_high") < names.index("stub_movie_low")
    confidences = [m["confidence"] for m in body]
    assert confidences == sorted(confidences, reverse=True)


def test_candidates_empty_signals_does_not_500(client):
    """No medium and no identifying fields is a valid, if unhelpful, query —
    it must return a (possibly empty) list, never a server error.

    Note: the provider registry is process-global across test modules, so
    other files' title-agnostic stubs may contribute matches here; this test
    only pins down the "must not crash" contract, not emptiness.
    """
    resp = client.post("/candidates", json={})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# POST /resolve — conflicts / dropped / provider_errors
# ---------------------------------------------------------------------------

def test_resolve_surfaces_provider_errors(client):
    resp = client.post("/resolve", json={"title": "Whatever", "medium": "movie"})
    assert resp.status_code == 200
    body = resp.json()
    errs = " ".join(str(e) for e in body["provider_errors"])
    assert "stub_movie_raises" in errs
    assert "upstream schema drift" in errs or "RuntimeError" in errs


def test_resolve_surfaces_conflicts_and_dropped(client):
    resp = client.post(
        "/resolve",
        json={"title": "Whatever", "year": 2010, "medium": "movie"},
    )
    assert resp.status_code == 200
    body = resp.json()
    dropped_providers = {m["provider"] for m in body["dropped"]}
    conflict_providers = {c["provider"] for c in body["conflicts"]}
    assert "stub_movie_conflict" in dropped_providers
    assert "stub_movie_conflict" in conflict_providers
    # the winning high-confidence match must still be accepted
    accepted_providers = {m["provider"] for m in body["accepted"]}
    assert "stub_movie_high" in accepted_providers


# ---------------------------------------------------------------------------
# POST /enrich
# ---------------------------------------------------------------------------

def test_enrich_round_trips_external_ids(client):
    resp = client.post(
        "/enrich",
        json={"external_ids": {"imdb": "tt1375666"}, "apply_maps": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["imdb"] == "tt1375666"


def test_enrich_empty_body_returns_empty_external_ids(client):
    resp = client.post("/enrich", json={})
    assert resp.status_code == 200
    body = resp.json()
    # No ids in, none conjured out of thin air for fields we didn't send.
    assert body.get("imdb") is None


def test_enrich_bad_medium_is_422_not_500(client):
    resp = client.post("/enrich", json={"external_ids": {}, "medium": "not-a-medium"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /ui/resolve (Form)
# ---------------------------------------------------------------------------

def test_ui_resolve_renders_candidate_cards_and_confidence_bars(client):
    resp = client.post("/ui/resolve", data={"title": "Whatever", "medium": "movie"})
    assert resp.status_code == 200
    html = resp.text
    assert "stub_movie_high" in html
    assert "stub_movie_low" in html
    # confidence rendered both as a percentage label and a bar width
    assert "95%" in html
    assert "width: 95.0%" in html or "width: 95%" in html


def test_ui_resolve_bad_medium_renders_inline_error_not_500(client):
    resp = client.post("/ui/resolve", data={"title": "Whatever", "medium": "not-a-medium"})
    assert resp.status_code == 200
    assert "invalid medium" in resp.text.lower()


def test_ui_resolve_empty_title_does_not_crash(client):
    """An entirely empty form (no title, no medium) must render a fragment,
    not 500 — an empty Signals() bag is a valid, if unhelpful, query.

    Note: the provider registry is process-global, so other test modules'
    registered stubs (e.g. test_server.py's title-agnostic stub_movie_test)
    may still contribute a candidate here — this only asserts the endpoint
    stays healthy and renders the fragment shell, not that it's empty.
    """
    resp = client.post("/ui/resolve", data={})
    assert resp.status_code == 200
    assert "Consolidated result" in resp.text
    assert "Ranked candidates" in resp.text


# ---------------------------------------------------------------------------
# /ui/providers
# ---------------------------------------------------------------------------

def _provider_card(html: str, provider_name: str) -> str:
    """Slice out one provider's `<div class="card">...</div>` block by name."""
    import re

    cards = re.findall(r'<div class="card">.*?</div>\s*</div>', html, flags=re.DOTALL)
    for card in cards:
        if f'>{provider_name}<' in card:
            return card
    raise AssertionError(f"no card found for provider {provider_name!r}")


def test_ui_providers_lists_available_and_unavailable(client):
    resp = client.get("/ui/providers")
    assert resp.status_code == 200
    html = resp.text
    # A stub with no key requirement must show up as available.
    assert "stub_movie_high" in html
    # TMDB is key-gated; unless a stray TMDB_API_KEY leaked into this test
    # environment it must render as unavailable.
    if not os.environ.get("TMDB_API_KEY"):
        card = _provider_card(html, "tmdb")
        assert "badge-err" in card
        assert "badge-ok" not in card
    assert "key-gated" in html.lower() or "TMDB_API_KEY" in html


def test_ui_providers_musicbrainz_is_available_keyless(client):
    """musicbrainz needs no API key and must always show as available."""
    resp = client.get("/ui/providers")
    assert resp.status_code == 200
    card = _provider_card(resp.text, "musicbrainz")
    assert "badge-ok" in card
    assert "badge-err" not in card


# ---------------------------------------------------------------------------
# /ui/mappings
# ---------------------------------------------------------------------------

def test_ui_mappings_renders_and_shows_paths(client):
    resp = client.get("/ui/mappings")
    assert resp.status_code == 200
    assert "mappings.toml" in resp.text


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------

def test_healthz_version_matches_package_version(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["version"] == __version__


# ---------------------------------------------------------------------------
# Static assets — guards package-data shipping (wheel install regressions)
# ---------------------------------------------------------------------------

def test_static_app_css_content_type(client):
    resp = client.get("/static/app.css")
    assert resp.status_code == 200
    assert "css" in resp.headers["content-type"]


def test_static_app_js_ok(client):
    resp = client.get("/static/app.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"] or "ecmascript" in resp.headers["content-type"]


def test_static_htmx_min_js_contains_htmx_banner(client):
    """Proves the vendored htmx build actually shipped, not an empty stub."""
    resp = client.get("/static/htmx.min.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"] or "ecmascript" in resp.headers["content-type"]
    assert "htmx" in resp.text.lower()


def test_create_app_resolves_templates_and_static_when_imported():
    """Guards package-data: create_app() must find templates/ and static/
    relative to the installed package, not the source checkout."""
    app = create_app()
    assert app is not None
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/static/app.css").status_code == 200


# ---------------------------------------------------------------------------
# Opt-in live network test
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("METADATARR_SKIP_NETWORK_TESTS", "1") == "1",
    reason="live network test — set METADATARR_SKIP_NETWORK_TESTS=0 to run",
)
def test_candidates_live_network(client):
    resp = client.post("/candidates", json={"title": "Inception", "year": 2010, "medium": "movie"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
