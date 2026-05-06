"""Resolver registry and consolidation."""
from typing import Optional

from metadatarr.resolve import (
    ExternalIds,
    MediaType,
    MetadataProvider,
    ProviderMatch,
    Signals,
    active_providers,
    all_providers,
    consolidate,
    register,
)
from metadatarr.resolve import ResolutionConflict  # noqa: F401


class _StubProvider(MetadataProvider):
    name = "stub_movie"
    media = {MediaType.MOVIE}

    def __init__(self, available: bool = True, match: Optional[ProviderMatch] = None):
        self._available = available
        self._match = match

    def is_available(self) -> bool:
        return self._available

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return self._match


def test_register_and_query():
    p = _StubProvider()
    register(p)
    assert "stub_movie" in all_providers()
    assert any(x.name == "stub_movie" for x in active_providers(medium=MediaType.MOVIE))


def test_unavailable_provider_filtered_out():
    register(_StubProvider(available=False))
    assert all(x.is_available() for x in active_providers())


def test_consolidate_accepts_matching():
    local = Signals(title="Inception", year=2010, medium=MediaType.MOVIE)
    match = ProviderMatch(
        provider="stub",
        confidence=0.9,
        signals=Signals(title="Inception", year=2010, medium=MediaType.MOVIE),
        external_ids=ExternalIds(tmdb_movie=27205),
    )
    result = consolidate([match], local=local)
    assert result.accepted == [match]
    assert result.dropped == []
    assert result.external_ids.tmdb_movie == 27205


def test_consolidate_anchors_on_highest_confidence():
    """Stronger match wins regardless of input order."""
    local = Signals(title="The Matrix", medium=MediaType.MOVIE)
    weak = ProviderMatch(
        provider="weak",
        confidence=0.3,
        signals=Signals(title="The Matrix", year=2003, medium=MediaType.MOVIE),
        external_ids=ExternalIds(tmdb_movie=999),
    )
    strong = ProviderMatch(
        provider="strong",
        confidence=0.95,
        signals=Signals(title="The Matrix", year=1999, medium=MediaType.MOVIE),
        external_ids=ExternalIds(tmdb_movie=603),
    )
    # Pass weak first; consolidate should still pick strong as the anchor.
    result = consolidate([weak, strong], local=local)
    assert strong in result.accepted
    assert weak in result.dropped
    # Strong's external ids — not weak's — populate the merged result.
    assert result.external_ids.tmdb_movie == 603


def test_consolidate_emits_conflict_diagnostics_local():
    local = Signals(title="Inception", year=2010, medium=MediaType.MOVIE)
    bad = ProviderMatch(
        provider="prov_b",
        confidence=0.5,
        signals=Signals(title="Inception", year=2020, medium=MediaType.MOVIE),
    )
    result = consolidate([bad], local=local)
    assert len(result.conflicts) == 1
    c = result.conflicts[0]
    assert c.provider == "prov_b"
    assert c.against == "local"
    assert any(f.signal == "year" for f in c.fields)


def test_consolidate_emits_conflict_diagnostics_against_anchor():
    """When conflict surfaces only after an anchor was accepted, the
    diagnostic names that anchor instead of "local"."""
    local = Signals(title="Inception", medium=MediaType.MOVIE)
    anchor = ProviderMatch(
        provider="prov_a",
        confidence=0.9,
        signals=Signals(title="Inception", year=2010, medium=MediaType.MOVIE),
    )
    later = ProviderMatch(
        provider="prov_b",
        confidence=0.5,
        signals=Signals(title="Inception", year=2020, medium=MediaType.MOVIE),
    )
    result = consolidate([anchor, later], local=local)
    drop_diag = [c for c in result.conflicts if c.provider == "prov_b"]
    assert drop_diag and drop_diag[0].against == "prov_a"


def test_external_ids_merge_first_writer_wins_extra():
    """`extra` keys from the higher-precedence source survive a later merge."""
    strong = ExternalIds(extra={"k": "from-strong"})
    weak = ExternalIds(extra={"k": "from-weak", "other": "v"})
    out = strong.merge(weak)
    assert out.extra["k"] == "from-strong"
    assert out.extra["other"] == "v"


def test_consolidate_drops_conflict_with_local():
    local = Signals(title="Inception", year=2010, medium=MediaType.MOVIE)
    bad = ProviderMatch(
        provider="stub",
        confidence=0.9,
        signals=Signals(title="Interstellar", year=2014, medium=MediaType.MOVIE),
        external_ids=ExternalIds(tmdb_movie=157336),
    )
    result = consolidate([bad], local=local)
    assert result.accepted == []
    assert result.dropped == [bad]
    assert result.external_ids.tmdb_movie is None
