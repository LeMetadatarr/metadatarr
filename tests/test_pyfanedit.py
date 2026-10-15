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


def test_list_variants_raises_on_client_error():
    """A failed fanedit.org search is not "no fan edits": it raises, so the
    resolver records it in provider_errors."""
    provider = PyfaneditProvider.__new__(PyfaneditProvider)
    provider._available = True
    mock_client = MagicMock()
    mock_client.search_by_original_title.side_effect = RuntimeError("network error")
    provider._client = mock_client
    with pytest.raises(RuntimeError, match="network error"):
        provider.list_variants(ExternalIds(), Signals(title="Alien"))


def test_failed_search_lands_in_provider_errors(monkeypatch):
    from metadatarr.resolve import base as resolve_base

    provider = PyfaneditProvider.__new__(PyfaneditProvider)
    provider._available = True
    provider._client = MagicMock()
    provider._client.search_by_original_title.side_effect = RuntimeError("fanedit.org answered HTTP 503")
    monkeypatch.setattr(resolve_base, "_REGISTRY", {"pyfanedit": provider})
    result = resolve_base.ResolveResult(signals=Signals(title="Alien", medium=MediaType.MOVIE))
    resolve_base.add_variants(result, Signals(title="Alien", medium=MediaType.MOVIE, include_variants=True))
    assert result.variants == []
    assert [(e.provider, e.stage, e.error_type) for e in result.provider_errors] == [
        ("pyfanedit", "variants", "RuntimeError")]


def test_list_variants_carries_the_listing_fields():
    from pyfanedit.models import FaneditSummary

    summary = FaneditSummary(title="Alien: FanFix", url="https://fanedit.org/alien-fanfix/", fanedit_type="FanFix",
                             original_title="Alien", faneditor="Placeholder Editor", release_date="2010-01-02",
                             running_time="1h 45m", synopsis="A placeholder.", cover_url="https://fanedit.org/c.jpg")
    entity, = _provider_with_mock([summary]).list_variants(ExternalIds(), Signals(title="Alien"))
    extra = entity.external_ids.extra
    assert {k: extra[k] for k in ("faneditor", "fanedit_release_date", "running_time", "synopsis", "cover_url",
                                  "edit_name", "fanedit_url")} == {
        "faneditor": "Placeholder Editor", "fanedit_release_date": "2010-01-02", "running_time": "1h 45m",
        "synopsis": "A placeholder.", "cover_url": "https://fanedit.org/c.jpg", "edit_name": "FanFix",
        "fanedit_url": "https://fanedit.org/alien-fanfix/"}
    assert entity.image_url == "https://fanedit.org/c.jpg"
    assert "available_in" not in extra and "release_information" not in extra


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


# ---------------------------------------------------------------------------
# Running times and edit names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,minutes", [
    ("1h 45m", 105.0), ("1h45m", 105.0), ("1H45M", 105.0), ("105 min", 105.0), ("105", 105.0),
    ("1:45", 105.0), ("1:45:00", 105.0), ("2:05:30", 125.0), ("1 hour, 52 minutes", 112.0),
    ("2 hrs 3 mins", 123.0), ("90m", 90.0), ("2h", 120.0), ("", None), (None, None), ("n/a", None),
    ("1h45", 105.0), ("1 h 30", 90.0), ("1,5h", 90.0), ("1.5h", 90.0), ("1,5 hours", 90.0), ("24:00", 1440.0),
    ("1h 75", 60.0), ("24h", 1440.0), ("1440", 1440.0), ("1440 min", 1440.0), ("1200 minutes", 1200.0),
    ("105 minutes (1h45)", 105.0), ("1h45 (105 min)", 105.0), ("90m / 1h30m", 90.0), ("1h 45m (105 min)", 105.0),
    ("1 hour and 52 minutes", 112.0),
])
def test_runtime_minutes_reads_every_ifdb_spelling(text, minutes):
    from metadatarr.catalog.sources.pyfanedit import runtime_minutes

    assert runtime_minutes(text) == minutes


@pytest.mark.parametrize("text", [
    "\u00b2", "\u00b3h", "1\u00b2m", "9" * 400, "9" * 5000, "9" * 400 + "h", "123:45", "1:75", "25h", "24:01", "0",
    "0h", "inf", "nan", "-5", "1 hello", "2 hourly", "90 mango", "45 minutesx", "h", ":", "1:2:3:4",
    "\u0663\u0660", "1\u00bd h", "1441", "9999", "1441 min",
])
def test_runtime_minutes_never_raises_and_rejects_nonsense(text):
    from metadatarr.catalog.sources.pyfanedit import runtime_minutes

    assert runtime_minutes(text) is None


@pytest.mark.parametrize("text,date", [
    ("April 2026", "2026-04"), ("april 2026", "2026-04"), ("Sept 2010", "2010-09"), ("Sep. 2010", "2010-09"),
    ("May 1999", "1999-05"), ("2026", "2026"), ("2026-04", "2026-04"), ("2026-04-02", "2026-04-02"),
    ("2026-04-02T10:00:00Z", "2026-04-02"), (" December 2001 ", "2001-12"),
    ("", None), (None, None), ("sometime soon", None), ("Smarch 2026", None), ("20260", None), ("202", None),
    ("April", None),
])
def test_release_date_reads_every_ifdb_spelling(text, date):
    from metadatarr.catalog.sources.pyfanedit import release_date

    assert release_date(text) == date


@pytest.mark.parametrize("title,original,name", [
    ("Alien: FanFix", "Alien", "FanFix"),
    ("Alien - The Second Cut", "Alien", "The Second Cut"),
    ("Alien \u2013 The Third Cut", "Alien", "The Third Cut"),
    ("Alien| Bar", "Alien", "Bar"),
    ("Alien/Cut", "Alien", "Cut"),
    ("Alien (Director's Cut)", "Alien", "(Director's Cut)"),
    ("Alien(Director's Cut)", "Alien", "(Director's Cut)"),
    ("Aliens: Special", "Alien", "Aliens: Special"),
    ("Alien3 Assembly", "Alien", "Alien3 Assembly"),
    ("Alien", "Alien", "Alien"),
    ("Alien: ", "Alien", "Alien:"),
    ("Something Else", "Alien", "Something Else"),
    ("X-Y 9.9: Z", "X-Y 9", "X-Y 9.9: Z"),
    ("Alien's Revenge", "Alien", "Alien's Revenge"),
    ("Alien_Cut", "Alien", "Alien_Cut"),
    ("Alien.Cut", "Alien", "Alien.Cut"),
    ("Alien, The Cut", "Alien", "Alien, The Cut"),
    ("Am\u00e9lie: Cut", "Am\u00e9lie", "Cut"),
    ("Ame\u0301lie: Cut", "Am\u00e9lie", "Cut"),
    ("Am\u00e9lie: Cut", "Ame\u0301lie", "Cut"),
    ("Cafe\u0301: Cut", "Cafe", "Cafe\u0301: Cut"),
])
def test_edit_name_strips_only_the_whole_film_title(title, original, name):
    from metadatarr.resolve.providers.pyfanedit import edit_name

    assert edit_name(title, original) == name


def test_list_variants_drops_edits_released_before_the_film():
    summaries = [
        _make_summary("Alien: Old", 1, "fanfix"), _make_summary("Alien: Same", 2, "fanfix"),
        _make_summary("Alien: Slack", 3, "fanfix"), _make_summary("Alien: Undated", 4, "fanfix"),
    ]
    for summary, released in zip(summaries, ["March 1990", "2021", "2020", None]):
        summary.release_date = released
    provider = _provider_with_mock(summaries)

    kept = provider.list_variants(ExternalIds(), Signals(title="Alien", year=2021))
    assert [e.external_ids.fanedit_id for e in kept] == [2, 3, 4]
    assert len(provider.list_variants(ExternalIds(), Signals(title="Alien"))) == 4


def test_no_provider_overrides_search_with_another_signature():
    import inspect

    from metadatarr.resolve.base import MetadataProvider, all_providers

    base = getattr(MetadataProvider, "search", None)
    for name, provider in all_providers().items():
        own = getattr(type(provider), "search", None)
        if base is None:
            assert own is None, f"{name} defines search before the base class does"
        elif own is not base:
            assert inspect.signature(own) == inspect.signature(base), name
