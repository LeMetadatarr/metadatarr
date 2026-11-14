"""The resolver fan-out consults only providers whose routing axes match."""
from typing import Optional
from unittest.mock import patch

import pytest
from mediavocab import PlaybackType

from metadatarr.resolve import (
    MediaType,
    MetadataProvider,
    ProviderMatch,
    Signals,
    active_providers,
    candidates,
    resolve,
)
from metadatarr.resolve import base
from metadatarr.resolve._cache import cache

NICHE = "niche-genre"


class _Recorder(MetadataProvider):
    """Provider that records every call; declares whatever axes it is given."""

    def __init__(self, name, media=(), playback_type=(), genre_filter=()):
        self.name = name
        self.media = set(media)
        self.playback_type = set(playback_type)
        self.genre_filter = set(genre_filter)
        self.calls = 0
        self.variant_calls = 0

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        self.calls += 1
        return None

    def list_variants(self, external_ids, signals=None):
        self.variant_calls += 1
        return []


@pytest.fixture(autouse=True)
def _isolated_registry():
    cache().clear()
    with patch.dict(base._REGISTRY, clear=True):
        yield
    cache().clear()


def _niche():
    provider = _Recorder("niche", media={MediaType.MOVIE}, genre_filter={NICHE})
    base.register(provider)
    return provider


def test_plain_movie_never_reaches_genre_gated_provider():
    niche = _niche()
    resolve(Signals(title="Inception", year=2010, medium=MediaType.MOVIE))
    candidates(Signals(title="Heat", year=1995, medium=MediaType.MOVIE))
    assert niche.calls == 0


def test_matching_genre_request_reaches_provider():
    niche = _niche()
    resolve(Signals(title="Some Title", medium=MediaType.MOVIE, content_genres=[NICHE]))
    assert niche.calls == 1


def test_provider_with_empty_axes_is_consulted_for_everything():
    open_provider = _Recorder("open")
    base.register(open_provider)
    for i, sig in enumerate([
        Signals(title="a", medium=MediaType.MOVIE),
        Signals(title="b", medium=MediaType.MUSIC),
        Signals(title="c", medium=MediaType.BOOK, content_genres=[NICHE]),
        Signals(title="d", playback_type=PlaybackType.AUDIO),
    ], start=1):
        resolve(sig)
        assert open_provider.calls == i


def test_playback_type_axis_is_enforced():
    audio_only = _Recorder("audio_only", media={MediaType.GENERIC},
                           playback_type={PlaybackType.AUDIO})
    base.register(audio_only)
    resolve(Signals(title="x", medium=MediaType.GENERIC, playback_type=PlaybackType.VIDEO))
    assert audio_only.calls == 0
    resolve(Signals(title="x", medium=MediaType.GENERIC, playback_type=PlaybackType.AUDIO))
    assert audio_only.calls == 1


def test_variants_fan_out_is_routed():
    niche = _niche()
    resolve(Signals(title="x", medium=MediaType.MOVIE, include_variants=True))
    assert niche.variant_calls == 0
    resolve(Signals(title="y", medium=MediaType.MOVIE, include_variants=True,
                    content_genres=[NICHE]))
    assert niche.variant_calls == 1


def test_active_providers_accepts_signals():
    niche = _niche()
    assert active_providers(signals=Signals(title="x", medium=MediaType.MOVIE)) == []
    assert active_providers(
        signals=Signals(title="x", medium=MediaType.MOVIE, content_genres=[NICHE])) == [niche]
    assert active_providers() == [niche]


class _BrokenMatches(_Recorder):
    def matches(self, signals):
        raise RuntimeError("matches exploded")


def test_provider_whose_matches_raises_does_not_break_the_fanout(caplog):
    base._MATCH_FAILED.clear()
    broken = _BrokenMatches("broken", media={MediaType.MOVIE})
    healthy = _Recorder("healthy", media={MediaType.MOVIE})
    base.register(broken)
    base.register(healthy)
    signals = Signals(title="X", medium=MediaType.MOVIE)

    with caplog.at_level("WARNING", logger="metadatarr.resolve"):
        resolve(signals)
        cache().clear()
        candidates(signals)
        cache().clear()
        resolve(signals)

    assert healthy.calls == 3
    assert broken.calls == 0
    assert [p.name for p in active_providers(MediaType.MOVIE, signals)] == ["healthy"]
    warnings = [r for r in caplog.records if "broken" in r.getMessage()]
    assert len(warnings) == 1
