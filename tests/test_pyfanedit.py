"""Tests for the pyfanedit provider and include_variants fan-out."""
from unittest.mock import MagicMock, patch

import pytest

from metadatarr.resolve.entities import EntityRole
from mediavocab.models import ExternalIds
from metadatarr.resolve.providers.pyfanedit import PyfaneditProvider, _FANEDIT_TYPE_MAP
from mediavocab import MediaType, VariantKind
from mediavocab.models.signals import Signals


def _make_summary(title, fanedit_id, fanedit_type, url="https://fanedit.org/test/"):
    from pyfanedit.models import FaneditSummary
    return FaneditSummary(
        title=title,
        url=url,
        fanedit_id=fanedit_id,
        fanedit_type=fanedit_type,
        original_title="Alien",
    )


# ---------------------------------------------------------------------------
# Provider basics
# ---------------------------------------------------------------------------

def test_pyfanedit_lookup_returns_none():
    """pyfanedit is a variant-only provider — lookup() must always return None."""
    provider = PyfaneditProvider()
    result = provider.lookup(Signals(title="Alien", medium=MediaType.MOVIE))
    assert result is None


def test_pyfanedit_media_set():
    provider = PyfaneditProvider()
    assert MediaType.MOVIE in provider.media


def test_pyfanedit_type_map_covers_all_ifdb_categories():
    """Every IFDB category slug should be in the type map."""
    for slug in ("fanfix", "fanmix", "extended", "tv_to_movie", "movie_to_tv",
                 "shorts", "special", "preservation", "documentary"):
        assert slug in _FANEDIT_TYPE_MAP, f"Missing IFDB category: {slug!r}"


# ---------------------------------------------------------------------------
# list_variants() — mocked HTTP
# ---------------------------------------------------------------------------

def _provider_with_mock(summaries):
    provider = PyfaneditProvider.__new__(PyfaneditProvider)
    provider._available = True
    mock_client = MagicMock()
    mock_client.search_by_original_title.return_value = summaries
    provider._client = mock_client
    return provider


def test_list_variants_returns_provider_entities():
    summaries = [
        _make_summary("Alien: FanFix",    fanedit_id=1001, fanedit_type="FanFix"),
        _make_summary("Alien: TV Edition", fanedit_id=1002, fanedit_type="FanMix"),
    ]
    provider = _provider_with_mock(summaries)

    signals = Signals(title="Alien", medium=MediaType.MOVIE)
    ids = ExternalIds(imdb="tt0078748")

    entities = provider.list_variants(ids, signals)

    assert len(entities) == 2
    assert all(e.role == EntityRole.OTHER for e in entities)
    assert entities[0].external_ids.fanedit_id == 1001
    assert entities[1].external_ids.fanedit_id == 1002


def test_list_variants_emits_correct_variant_kinds():
    summaries = [
        _make_summary("FanFix Edit",      1001, "fanfix"),
        _make_summary("FanMix Edit",      1002, "fanmix"),
        _make_summary("Extended Cut",     1003, "extended"),
        _make_summary("TV Movie Cut",     1004, "tv_to_movie"),
        _make_summary("Movie to TV",      1005, "movie_to_tv"),
        _make_summary("Short Edit",       1006, "shorts"),
        _make_summary("Preservation",     1007, "preservation"),
        _make_summary("Unknown Type",     1008, "something_new"),
    ]
    provider = _provider_with_mock(summaries)
    entities = provider.list_variants(ExternalIds(), Signals(title="Alien"))
    kinds = {e.external_ids.fanedit_id: e.external_ids.extra["fanedit_variant_kind"]
             for e in entities}
    subtypes = {e.external_ids.fanedit_id: e.external_ids.extra.get("fanedit_subtype")
                for e in entities}

    # FANFIX / FANMIX / FANEDIT_SHORT are not in mediavocab's VariantKind
    # (foundation excludes sub-types per spec §4.2). They surface as
    # variant_kind=FANEDIT plus a fanedit_subtype free-text tag.
    assert kinds[1001] == VariantKind.FANEDIT.value
    assert subtypes[1001] == "fanfix"
    assert kinds[1002] == VariantKind.FANEDIT.value
    assert subtypes[1002] == "fanmix"
    assert kinds[1003] == VariantKind.EXTENDED.value
    assert kinds[1004] == VariantKind.TV_TO_MOVIE.value
    assert kinds[1005] == VariantKind.MOVIE_TO_TV.value
    assert kinds[1006] == VariantKind.FANEDIT.value
    assert subtypes[1006] == "fanedit_short"
    assert kinds[1007] == VariantKind.PRESERVATION.value
    assert kinds[1008] == VariantKind.OTHER.value   # unknown → OTHER


def test_list_variants_propagates_derived_from_imdb():
    summaries = [_make_summary("Edit", 42, "fanfix")]
    provider = _provider_with_mock(summaries)
    ids = ExternalIds(imdb="tt0078748")
    signals = Signals(title="Alien", medium=MediaType.MOVIE)
    entities = provider.list_variants(ids, signals)
    assert len(entities) == 1
    assert entities[0].external_ids.derived_from_imdb == "tt0078748"


def test_list_variants_empty_when_unavailable():
    provider = PyfaneditProvider.__new__(PyfaneditProvider)
    provider._available = False
    provider._client = None
    assert provider.list_variants(ExternalIds(), None) == []


def test_list_variants_empty_on_client_error():
    provider = PyfaneditProvider.__new__(PyfaneditProvider)
    provider._available = True
    mock_client = MagicMock()
    mock_client.search_by_original_title.side_effect = RuntimeError("network error")
    provider._client = mock_client
    result = provider.list_variants(ExternalIds(), Signals(title="Alien"))
    assert result == []


# ---------------------------------------------------------------------------
# include_variants integration — resolve() fan-out
# ---------------------------------------------------------------------------

def test_resolve_include_variants_populates_variants():
    """include_variants=True should trigger list_variants() and populate result.variants."""
    summaries = [
        _make_summary("Alien: FanFix v1",  9901, "fanfix"),
        _make_summary("Alien: TV Cut",     9902, "tv_to_movie"),
    ]

    signals = Signals(title="Alien", medium=MediaType.MOVIE, include_variants=True)

    ids = ExternalIds(imdb="tt0078748")
    mock_provider = _provider_with_mock(summaries)

    variants = mock_provider.list_variants(ids, signals)
    fanedit_ids = {e.external_ids.fanedit_id for e in variants}
    assert 9901 in fanedit_ids
    assert 9902 in fanedit_ids
    assert len(variants) == 2
