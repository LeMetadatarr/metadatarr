"""metadatarr.resolve.search() — ranked candidate union, no consolidation."""
from typing import List, Optional

import pytest

from metadatarr.resolve import (
    ExternalIds,
    MediaType,
    MetadataProvider,
    ProviderMatch,
    Signals,
    search,
)
from metadatarr.resolve._cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    cache().clear()
    yield
    cache().clear()


def _match(provider: str, conf: float, year: int = 2010, **ids) -> ProviderMatch:
    return ProviderMatch(
        provider=provider, confidence=conf,
        signals=Signals(title="X", year=year, medium=MediaType.MOVIE),
        external_ids=ExternalIds(**ids),
    )


class _Stub(MetadataProvider):
    def __init__(self, name: str, candidates: List[ProviderMatch]):
        self.name = name
        self.media = {MediaType.MOVIE}
        self._cands = candidates

    def is_available(self) -> bool:
        return True

    def lookup(self, signals):
        return self._cands[0] if self._cands else None

    def lookup_candidates(self, signals):
        return list(self._cands)


def test_search_returns_ranked_union(monkeypatch):
    a = _Stub("a", [_match("a", 0.9, tmdb_movie=1), _match("a", 0.5, tmdb_movie=2)])
    b = _Stub("b", [_match("b", 0.7, tmdb_movie=3)])
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [a, b],
    )
    out = search(Signals(title="X", medium=MediaType.MOVIE))
    assert [m.confidence for m in out] == sorted(
        [m.confidence for m in out], reverse=True,
    )
    # All candidates surface — no consolidation
    assert {m.external_ids.tmdb_movie for m in out} == {1, 2, 3}


def test_search_empty_when_no_providers(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [],
    )
    assert search(Signals(title="X", medium=MediaType.MOVIE)) == []


def test_search_filters_by_medium(monkeypatch):
    movie_only = _Stub("movie", [_match("movie", 0.9, tmdb_movie=1)])
    movie_only.media = {MediaType.MOVIE}
    music_only = _Stub("music", [_match("music", 0.9, tmdb_movie=99)])
    music_only.media = {MediaType.MUSIC}

    def fake_active(medium=None):
        if medium == MediaType.MOVIE:
            return [movie_only]
        if medium == MediaType.MUSIC:
            return [music_only]
        return [movie_only, music_only]

    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers", fake_active,
    )
    out = search(Signals(title="X", medium=MediaType.MOVIE))
    assert {m.provider for m in out} == {"movie"}


def test_search_swallows_provider_exceptions(monkeypatch):
    class Boom(MetadataProvider):
        name = "boom"
        media = {MediaType.MOVIE}
        def is_available(self): return True
        def lookup(self, s): return None
        def lookup_candidates(self, s):
            raise RuntimeError("upstream broke")

    good = _Stub("good", [_match("good", 0.5, tmdb_movie=42)])
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [Boom(), good],
    )
    out = search(Signals(title="X", medium=MediaType.MOVIE))
    # Boom contributed nothing; good still surfaces.
    assert [m.provider for m in out] == ["good"]


def test_search_compose_with_consolidate(monkeypatch):
    """`consolidate(search(s), s)` reproduces resolve()'s shape."""
    from metadatarr.resolve import consolidate

    a = _Stub("a", [_match("a", 0.9, tmdb_movie=1)])
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: [a],
    )
    sig = Signals(title="X", year=2010, medium=MediaType.MOVIE)
    cand = search(sig)
    result = consolidate(cand, sig)
    assert result.external_ids.tmdb_movie == 1
