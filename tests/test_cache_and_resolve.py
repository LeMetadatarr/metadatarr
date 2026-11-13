"""Provider lookup cache + concurrent resolve()."""
import threading
import time
from typing import Optional

import pytest

from metadatarr.resolve import (
    ExternalIds,
    MediaType,
    MetadataProvider,
    ProviderMatch,
    Signals,
    register,
    resolve,
)
from metadatarr.resolve._cache import cache, cached_lookup


@pytest.fixture(autouse=True)
def _clear_cache():
    cache().clear()
    yield
    cache().clear()


class _Counted(MetadataProvider):
    """Counts calls so we can confirm cache hit/miss behaviour."""

    def __init__(self, name: str, match: Optional[ProviderMatch] = None,
                 boom: bool = False, sleep: float = 0.0):
        self.name = name
        self.media = {MediaType.MOVIE}
        self._match = match
        self._boom = boom
        self._sleep = sleep
        self.calls = 0
        self.lock = threading.Lock()

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        with self.lock:
            self.calls += 1
        if self._sleep:
            time.sleep(self._sleep)
        if self._boom:
            raise RuntimeError("boom")
        return self._match


def _match(name: str, conf: float = 0.8, **ext) -> ProviderMatch:
    return ProviderMatch(
        provider=name, confidence=conf,
        signals=Signals(title="X", medium=MediaType.MOVIE),
        external_ids=ExternalIds(**ext),
    )


def test_cached_lookup_memoises_hit():
    p = _Counted("c1", match=_match("c1", tmdb_movie=1))
    s = Signals(title="X", medium=MediaType.MOVIE)
    a = cached_lookup(p, s)
    b = cached_lookup(p, s)
    assert a is b is not None
    assert p.calls == 1


def test_cached_lookup_memoises_miss():
    p = _Counted("c2", match=None)
    s = Signals(title="X", medium=MediaType.MOVIE)
    assert cached_lookup(p, s) is None
    assert cached_lookup(p, s) is None
    assert p.calls == 1


def test_cached_lookup_propagates_provider_exception():
    p = _Counted("c3", boom=True)
    s = Signals(title="X", medium=MediaType.MOVIE)
    with pytest.raises(RuntimeError):
        cached_lookup(p, s)
    # A failed lookup is NOT cached — the provider is retried on each call.
    with pytest.raises(RuntimeError):
        cached_lookup(p, s)
    assert p.calls == 2


def test_resolve_runs_providers_concurrently(monkeypatch):
    """Concurrency: total wall time should be much closer to one provider's
    sleep than the sum of sleeps."""
    slow_a = _Counted("slow_a", match=_match("slow_a", tmdb_movie=1), sleep=0.1)
    slow_b = _Counted("slow_b", match=_match("slow_b", tmdb_movie=1), sleep=0.1)
    # Force resolve() to see only our two stub providers.
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [slow_a, slow_b],
    )
    s = Signals(title="X", medium=MediaType.MOVIE)
    t0 = time.perf_counter()
    result = resolve(s)
    elapsed = time.perf_counter() - t0
    # Sequential would be ~0.20s; concurrent should land well under 0.18s.
    assert elapsed < 0.18, f"resolve took {elapsed:.3f}s, expected concurrent <0.18s"
    assert any(m.provider == "slow_a" for m in result.accepted)


def test_resolve_uses_cache_on_repeat(monkeypatch):
    p = _Counted("only", match=_match("only", tmdb_movie=42))
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [p],
    )
    s = Signals(title="X", medium=MediaType.MOVIE)
    resolve(s)
    resolve(s)
    assert p.calls == 1


def test_resolve_consumes_lookup_candidates(monkeypatch):
    """A provider that returns multiple candidates feeds them all to consolidate."""

    class MultiProvider(MetadataProvider):
        name = "multi"
        media = {MediaType.MOVIE}

        def is_available(self) -> bool:
            return True

        def lookup(self, signals):  # required by ABC
            return None

        def lookup_candidates(self, signals):
            return [
                ProviderMatch(
                    provider=self.name, confidence=0.9,
                    signals=Signals(title="X", year=2010, medium=MediaType.MOVIE),
                    external_ids=ExternalIds(tmdb_movie=1),
                ),
                ProviderMatch(
                    provider=self.name, confidence=0.4,
                    signals=Signals(title="X", year=2099, medium=MediaType.MOVIE),
                    external_ids=ExternalIds(tmdb_movie=2),
                ),
            ]

    p = MultiProvider()
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [p],
    )
    result = resolve(Signals(title="X", year=2010, medium=MediaType.MOVIE))
    accepted = [m.external_ids.tmdb_movie for m in result.accepted]
    assert 1 in accepted
    # Year 2099 conflicts with local 2010 → low-confidence candidate dropped.
    assert 2 not in accepted


def test_resolve_handles_no_providers(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [],
    )
    result = resolve(Signals(title="X", medium=MediaType.MOVIE))
    assert result.accepted == []
