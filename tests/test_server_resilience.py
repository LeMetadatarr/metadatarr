# SPDX-License-Identifier: Apache-2.0
"""Adversarial hardening tests for the P0 fan-out hang and the info-leak /
honest-healthz findings.

- A provider that black-holes (never raises, never returns) must not hang
  ``resolve()``/``candidates()`` forever — the fan-out has a wall-clock
  deadline (see ``metadatarr.resolve.base._run_pool``). Fail-before: with the
  pre-fix ``_run_pool`` (plain ``pool.map`` with no timeout), the reproducer
  in this file blocks until the sleeping provider wakes up (~5s here, and
  unboundedly for a real dead TCP connect) — i.e. it exceeds any short
  deadline. This is demonstrated by asserting wall-clock elapsed stays under
  ``deadline + epsilon``, which the unfixed code cannot satisfy for a
  provider that sleeps longer than the deadline.
- ``make_session()``'s adapter must inject a default request timeout so a
  sibling call site that forgets ``timeout=`` still can't block forever.
- ``/healthz`` must report provider availability, not just a static 200.
- Unhandled exceptions in the JSON routes must not leak their raw message
  text to the client; the real exception is still logged.
"""
from __future__ import annotations

import logging
import time
from typing import Optional
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from metadatarr.resolve.base import (  # noqa: E402
    MetadataProvider,
    ProviderMatch,
    candidates,
    register,
    resolve,
)
from metadatarr.resolve._cache import cache  # noqa: E402
from metadatarr.server.app import create_app  # noqa: E402
from mediavocab import MediaType  # noqa: E402
from mediavocab.models import ExternalIds  # noqa: E402
from mediavocab.models.signals import Signals  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    cache().clear()
    yield
    cache().clear()


def _only(monkeypatch, *providers):
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: list(providers),
    )


class _SleepyProvider(MetadataProvider):
    """Simulates a provider black-holed on a TCP connect: never raises,
    just never comes back within any reasonable test window."""

    name = "sleepy_test_provider"
    media = {MediaType.MOVIE}

    def __init__(self, sleep_seconds: float) -> None:
        self._sleep_seconds = sleep_seconds

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        time.sleep(self._sleep_seconds)
        return ProviderMatch(
            provider=self.name, confidence=0.5,
            signals=Signals(title="late", medium=MediaType.MOVIE),
            external_ids=ExternalIds(tmdb_movie=999),
        )


class _FastProvider(MetadataProvider):
    name = "fast_test_provider"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return ProviderMatch(
            provider=self.name, confidence=0.9,
            signals=Signals(title="X", medium=MediaType.MOVIE),
            external_ids=ExternalIds(tmdb_movie=1),
        )


class _OrderProvider(MetadataProvider):
    """Equal-confidence stub used to detect fan-out result reordering.

    All instances return the same confidence, so `_run_pool`'s output order
    is the only thing that decides tie-break order downstream (stable sort
    in `candidates()`/`consolidate()`). `sleep` staggers completion times so
    a bug that leaks completion (or arbitrary hash-set) order instead of
    provider submission order has a real chance to show up.
    """

    media = {MediaType.MOVIE}

    def __init__(self, name: str, sleep: float) -> None:
        self.name = name
        self._sleep = sleep

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        time.sleep(self._sleep)
        return ProviderMatch(
            provider=self.name, confidence=0.5,
            signals=Signals(title="X", medium=MediaType.MOVIE),
            external_ids=ExternalIds(),
        )


class _RaisingProvider(MetadataProvider):
    """Raises with a message that must never reach the HTTP client verbatim."""

    name = "raising_test_provider"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        raise RuntimeError("super-secret-internal-detail-should-not-leak")


# ---------------------------------------------------------------------------
# Fan-out deadline
# ---------------------------------------------------------------------------

def test_resolve_returns_within_deadline_despite_hung_provider(monkeypatch):
    """The core P0 regression test: a provider that never raises and never
    returns must not hang resolve(). Deadline is short (1s) and the
    provider sleeps much longer (5s) so an unbounded pool.map would clearly
    exceed the assertion below; the fixed fan-out must return within
    deadline + a small epsilon instead of waiting out the full 5s sleep."""
    _only(monkeypatch, _SleepyProvider(sleep_seconds=5.0), _FastProvider())

    start = time.monotonic()
    result = resolve(Signals(title="X", medium=MediaType.MOVIE), deadline=1.0)
    elapsed = time.monotonic() - start

    assert elapsed < 3.0, (
        f"resolve() took {elapsed:.2f}s with a 1.0s deadline — "
        "the fan-out is not bounding the hung provider"
    )
    # The slow provider must be absent from accepted results...
    assert all(m.provider != "sleepy_test_provider" for m in result.accepted)
    # ...and a timeout must be recorded so callers can tell "hung" apart
    # from "no match".
    timeout_errors = [e for e in result.provider_errors
                       if e.provider == "sleepy_test_provider"]
    assert len(timeout_errors) == 1
    assert timeout_errors[0].error_type == "TimeoutError"
    # The fast provider still contributes — partial results, not a total wipe.
    assert result.external_ids.tmdb_movie == 1


def test_candidates_returns_within_deadline_despite_hung_provider(monkeypatch):
    _only(monkeypatch, _SleepyProvider(sleep_seconds=5.0), _FastProvider())

    start = time.monotonic()
    matches = candidates(Signals(title="X", medium=MediaType.MOVIE), deadline=1.0)
    elapsed = time.monotonic() - start

    assert elapsed < 3.0
    assert [m.provider for m in matches] == ["fast_test_provider"]


def test_resolve_deadline_none_waits_for_all_providers(monkeypatch):
    """deadline=None preserves the old wait-forever-per-round behaviour for
    callers that explicitly opt into it (short sleep here to keep the test
    fast; this is testing the *plumbing*, not the default)."""
    _only(monkeypatch, _SleepyProvider(sleep_seconds=0.2), _FastProvider())
    result = resolve(Signals(title="X", medium=MediaType.MOVIE), deadline=None)
    # The sleepy provider's signals ("late") clash with local ("X") and get
    # dropped by consolidate() — that's ordinary conflict handling, not a
    # timeout. What matters here is it was *waited for*, not dropped as a
    # timeout: no TimeoutError provider_error was recorded for it.
    timeouts = [e for e in result.provider_errors
                if e.provider == "sleepy_test_provider" and e.error_type == "TimeoutError"]
    assert timeouts == []


# ---------------------------------------------------------------------------
# Fan-out result order determinism
#
# `_run_pool` must return results in provider *input* order (matching the
# old `pool.map` contract), not in whatever order `concurrent.futures.wait`'s
# `done` set happens to iterate in. `consolidate()`/`candidates()` stable-sort
# by confidence, so for equal-confidence matches the tie-break is exactly
# this function's output order — an unordered `done` set makes which match
# gets accepted vs. dropped in conflict resolution nondeterministic.
# ---------------------------------------------------------------------------

def test_run_pool_preserves_provider_order_for_equal_confidence(monkeypatch):
    providers = [_OrderProvider(f"P{i}", sleep=(5 - i) * 0.02) for i in range(5)]
    _only(monkeypatch, *providers)
    expected_order = [p.name for p in providers]

    for _ in range(15):
        matches = candidates(Signals(title="X", medium=MediaType.MOVIE), deadline=5.0)
        assert [m.provider for m in matches] == expected_order


def test_set_iteration_based_run_pool_is_order_nondeterministic(monkeypatch):
    """Fail-before demonstration: this reproduces the just-fixed buggy
    `_run_pool` (building `results` by iterating `done`, a set, instead of
    the provider-ordered `futures` dict) and shows it does NOT reliably
    preserve provider submission order the way `pool.map` (and the fixed
    `_run_pool`) do."""
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import wait as cf_wait

    def buggy_run_pool(providers, fn, max_workers, *, deadline=None,
                        sink=None, stage="lookup"):
        if not providers:
            return []
        workers = max(1, min(max_workers, len(providers)))
        pool = ThreadPoolExecutor(max_workers=workers)
        futures = {pool.submit(fn, p): p for p in providers}
        results = []
        try:
            done, _not_done = cf_wait(futures, timeout=deadline)
            for fut in done:  # <-- the bug: unordered set iteration
                results.append(fut.result())
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return results

    monkeypatch.setattr("metadatarr.resolve.base._run_pool", buggy_run_pool)

    providers = [_OrderProvider(f"P{i}", sleep=(5 - i) * 0.02) for i in range(5)]
    _only(monkeypatch, *providers)
    expected_order = [p.name for p in providers]

    orders = []
    for _ in range(30):
        matches = candidates(Signals(title="X", medium=MediaType.MOVIE), deadline=5.0)
        orders.append([m.provider for m in matches])

    assert any(order != expected_order for order in orders), (
        "expected the set-iteration-based _run_pool to produce at least one "
        "run whose result order diverges from provider submission order over "
        "30 trials — if this assertion itself starts failing, the boundary "
        "condition being exploited (small `done`-set hash-iteration order vs. "
        "submission order) isn't manifesting here; that's evidence about test "
        "environment hash/GC layout, not that the original bug was safe."
    )


# ---------------------------------------------------------------------------
# Transport default timeout
# ---------------------------------------------------------------------------

def test_adapter_injects_default_timeout_when_omitted():
    from metadatarr.transport import CachingRateLimitedAdapter, HostRateLimiter, _DEFAULT_REQUEST_TIMEOUT

    adapter = CachingRateLimitedAdapter(HostRateLimiter())
    import requests.adapters as ra
    captured = {}

    def _fake_super_send(self, request, **kwargs):
        captured.update(kwargs)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    request = MagicMock()
    request.url = "https://example.invalid/x"
    request.method = "GET"
    request.body = None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ra.HTTPAdapter, "send", _fake_super_send)
        adapter.send(request)

    assert captured.get("timeout") == _DEFAULT_REQUEST_TIMEOUT


def test_adapter_preserves_explicit_timeout():
    from metadatarr.transport import CachingRateLimitedAdapter, HostRateLimiter

    adapter = CachingRateLimitedAdapter(HostRateLimiter())
    captured = {}
    import requests.adapters as ra

    def _fake_super_send(self, request, **kwargs):
        captured.update(kwargs)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    request = MagicMock()
    request.url = "https://example.invalid/x"
    request.method = "GET"
    request.body = None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ra.HTTPAdapter, "send", _fake_super_send)
        adapter.send(request, timeout=42)

    assert captured.get("timeout") == 42


# ---------------------------------------------------------------------------
# Server: healthz + generic 500s
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


def test_healthz_reports_provider_counts(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert "providers_available" in body
    assert "providers_total" in body
    assert isinstance(body["providers_available"], int)
    assert isinstance(body["providers_total"], int)
    assert 0 <= body["providers_available"] <= body["providers_total"]


def test_resolve_500_does_not_leak_exception_text(client, monkeypatch, caplog):
    _only(monkeypatch, _RaisingProvider())

    def _boom(*a, **k):
        raise RuntimeError("super-secret-internal-detail-should-not-leak")

    monkeypatch.setattr("metadatarr.server.routes.run_resolve", _boom)

    with caplog.at_level(logging.ERROR, logger="metadatarr.server.routes"):
        resp = client.post("/resolve", json={"title": "X", "medium": "movie"})

    assert resp.status_code == 500
    assert "super-secret-internal-detail-should-not-leak" not in resp.text
    assert resp.json()["detail"] == "internal error during resolve"
    # ...but the real exception is still logged server-side.
    assert any("super-secret-internal-detail-should-not-leak" in r.getMessage()
               or "super-secret-internal-detail-should-not-leak" in (r.exc_text or "")
               for r in caplog.records)


def test_candidates_500_does_not_leak_exception_text(client, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("another-secret-detail")

    monkeypatch.setattr("metadatarr.server.routes.run_candidates", _boom)
    resp = client.post("/candidates", json={"title": "X", "medium": "movie"})
    assert resp.status_code == 500
    assert "another-secret-detail" not in resp.text
    assert resp.json()["detail"] == "internal error during candidates"


def test_enrich_500_does_not_leak_exception_text(client, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("yet-another-secret")

    monkeypatch.setattr("metadatarr.server.routes.run_enrich", _boom)
    resp = client.post("/enrich", json={"external_ids": {}})
    assert resp.status_code == 500
    assert "yet-another-secret" not in resp.text
    assert resp.json()["detail"] == "internal error during enrich"


def test_enrich_422_validation_path_still_specific(client):
    """The 422 validation paths (unlike the 500 path) are fine to stay specific."""
    resp = client.post("/enrich", json={"external_ids": {}, "medium": "bogus"})
    assert resp.status_code == 422
    assert "bogus" in resp.text
