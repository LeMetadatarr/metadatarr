"""Tests for the MAL provider (offline — pymal network is patched)."""
from __future__ import annotations

from unittest.mock import patch

from mediavocab.models.signals import Signals

from metadatarr.resolve.providers.mal import MALProvider


def _card(mal_id=1, title="Naruto", url="https://myanimelist.net/anime/1/Naruto"):
    from pymal.models import AnimeCard
    return AnimeCard(
        mal_id=mal_id,
        title=title,
        url=url,
        image_url="",
    )


def test_exact_match_high_confidence():
    p = MALProvider()
    card = _card(mal_id=20, title="Naruto", url="https://myanimelist.net/anime/20/Naruto")
    with patch("pymal.search.search_anime", return_value=[card]):
        m = p.lookup(Signals(title="Naruto"))
    assert m is not None
    assert m.confidence >= 0.90
    assert m.external_ids.extra["mal_id"] == 20
    assert "myanimelist" in m.external_ids.extra["mal_url"]


def test_partial_match_lower_confidence():
    p = MALProvider()
    card = _card(mal_id=21, title="Naruto Shippuden",
                 url="https://myanimelist.net/anime/21/Naruto_Shippuden")
    with patch("pymal.search.search_anime", return_value=[card]):
        m = p.lookup(Signals(title="Naruto"))
    assert m is not None
    assert m.confidence < 0.90


def test_no_results_returns_none():
    p = MALProvider()
    with patch("pymal.search.search_anime", return_value=[]):
        m = p.lookup(Signals(title="Naruto"))
    assert m is None


def test_exception_returns_none():
    p = MALProvider()
    with patch("pymal.search.search_anime", side_effect=Exception("network error")):
        m = p.lookup(Signals(title="Naruto"))
    assert m is None


def test_empty_title_returns_none():
    p = MALProvider()
    m = p.lookup(Signals())
    assert m is None


def test_is_available():
    assert MALProvider().is_available() is True
