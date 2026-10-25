# SPDX-License-Identifier: Apache-2.0
"""The offline layer in front of the resolver, the enrichment and the
catalogue: hit, miss, refresh, stale rows, damaged input and the origin each
answer reports. Live providers are fakes that count their calls."""
from __future__ import annotations

import json
from typing import Optional

import pytest

pytest.importorskip("pyarrow")

from mediavocab import MediaType  # noqa: E402
from mediavocab.models import ExternalIds  # noqa: E402
from mediavocab.models.signals import Signals  # noqa: E402

from metadatarr import catalog  # noqa: E402
from metadatarr.catalog import base as catalog_base  # noqa: E402
from metadatarr.catalog.shapes import Item  # noqa: E402
from metadatarr.offline import build, layer  # noqa: E402
from metadatarr.offline.config import OfflineConfig  # noqa: E402
from metadatarr.offline.sets import BY_NAME  # noqa: E402
from metadatarr.offline.store import Store  # noqa: E402
from metadatarr.resolve import _cache  # noqa: E402
from metadatarr.resolve import base as resolve_base  # noqa: E402
from metadatarr.resolve.base import MetadataProvider, ProviderMatch  # noqa: E402
from metadatarr.transport import bypass_cache  # noqa: E402
from tests._offline_fixtures import SAMPLES, write_shard  # noqa: E402

BUILT_AT = 1000.0
MAX_AGE = 100.0
SETS = ("tvmaze-shows", "anilist-anime", "openlibrary-books", "unified-artists", "steam-games", "jikan-manga")


class Clock:
    now = BUILT_AT + 10


@pytest.fixture
def offline(tmp_path):
    for name in SETS:
        spec = BY_NAME[name]
        shard = write_shard(tmp_path / "shards" / f"{name}.parquet", [SAMPLES[name]["row"]])
        build.build_set(spec, [shard], tmp_path / "data", dataset=spec.repo, revision=f"rev-{name}",
                        clock=lambda: BUILT_AT)
    clock = Clock()
    layer.configure(OfflineConfig(data_dir=tmp_path / "data", max_age=MAX_AGE), clock=lambda: clock.now)
    _cache.cache().clear()
    catalog.reset_cache()
    yield clock
    layer.configure(None)
    _cache.cache().clear()
    catalog.reset_cache()


class Live(MetadataProvider):
    """A live provider named after the one a set fronts; counts what it is asked."""

    media = set()

    def __init__(self, name, medium=MediaType.EPISODIC_SERIES, enriches: Optional[ExternalIds] = None):
        self.name, self._medium, self._enrichment = name, medium, enriches
        self.lookups = self.enrichments = 0

    def is_available(self):
        return True

    def lookup(self, signals):
        self.lookups += 1
        return ProviderMatch(provider=self.name, confidence=0.5,
                             signals=Signals(title=signals.title, medium=self._medium),
                             external_ids=ExternalIds(imdb="ttLIVE"))

    def enrich(self, external_ids):
        self.enrichments += 1
        return self._enrichment


class LiveWithoutEnrich(Live):
    enrich = MetadataProvider.enrich


def serve(monkeypatch, *providers):
    monkeypatch.setattr(resolve_base, "active_providers", lambda medium=None, signals=None: list(providers))


def show(title="Under the Dome", medium=MediaType.EPISODIC_SERIES, **kw):
    return Signals(title=title, medium=medium, **kw)


# -- title search ------------------------------------------------------------------------

def test_a_hit_is_answered_offline_and_the_live_provider_is_not_asked(offline, monkeypatch):
    live = Live("tvmaze")
    serve(monkeypatch, live)
    (match,) = resolve_base.candidates(show())
    assert live.lookups == 0
    assert match.provider == "tvmaze"
    assert match.signals.title == "Under the Dome" and match.signals.year == 2013
    assert match.external_ids.tvdb == 264492 and match.external_ids.tvmaze == 1
    assert match.external_ids.imdb == "tt1553656"
    assert match.origin == {"source": "offline", "dataset": "LeData/media-metadata-tvmaze-shows",
                            "revision": "rev-tvmaze-shows", "built_at": "1970-01-01T00:16:40Z"}
    assert 0 < match.confidence <= layer.CONFIDENCE


def test_a_miss_falls_through_to_the_live_provider(offline, monkeypatch):
    live = Live("tvmaze")
    serve(monkeypatch, live)
    (match,) = resolve_base.candidates(show("A Show Nobody Indexed"))
    assert live.lookups == 1
    assert match.external_ids.imdb == "ttLIVE"
    assert match.origin == layer.LIVE


def test_refresh_bypasses_the_offline_row(offline, monkeypatch):
    live = Live("tvmaze")
    serve(monkeypatch, live)
    with bypass_cache(True):
        (match,) = resolve_base.candidates(show())
    assert live.lookups == 1 and match.origin == layer.LIVE


def test_a_row_older_than_the_maximum_age_falls_through(offline, monkeypatch):
    live = Live("tvmaze")
    serve(monkeypatch, live)
    offline.now = BUILT_AT + MAX_AGE
    assert resolve_base.candidates(show())[0].origin["source"] == "offline"
    offline.now = BUILT_AT + MAX_AGE + 1
    (match,) = resolve_base.candidates(show())
    assert live.lookups == 1 and match.origin == layer.LIVE


def test_a_maximum_age_of_zero_never_expires(tmp_path, offline, monkeypatch):
    layer.configure(OfflineConfig(data_dir=tmp_path / "data", max_age=0), clock=lambda: 10**12)
    live = Live("tvmaze")
    serve(monkeypatch, live)
    assert resolve_base.candidates(show())[0].origin["source"] == "offline"
    assert live.lookups == 0


def test_the_layer_off_changes_nothing_in_the_response(tmp_path, offline, monkeypatch):
    layer.configure(OfflineConfig())
    live = Live("tvmaze")
    serve(monkeypatch, live)
    (match,) = resolve_base.candidates(show())
    assert live.lookups == 1 and match.origin is None
    assert "origin" not in match.model_dump()
    assert "origin" not in json.loads(match.model_dump_json())


def test_origin_is_in_the_serialised_match_when_the_layer_is_on(offline, monkeypatch):
    serve(monkeypatch, Live("tvmaze"))
    (match,) = resolve_base.candidates(show())
    assert json.loads(match.model_dump_json())["origin"]["source"] == "offline"


def test_an_unset_medium_or_a_medium_the_set_does_not_cover_is_asked_live(offline, monkeypatch):
    live = Live("tvmaze")
    serve(monkeypatch, live)
    resolve_base.candidates(show(medium=None))
    resolve_base.candidates(show(medium=MediaType.MOVIE))
    assert live.lookups == 2


def test_a_provider_no_set_fronts_is_untouched(offline, monkeypatch):
    live = Live("tmdb", medium=MediaType.MOVIE)
    serve(monkeypatch, live)
    (match,) = resolve_base.candidates(show("Under the Dome", medium=MediaType.MOVIE))
    assert live.lookups == 1 and match.origin == layer.LIVE


def test_the_title_is_matched_whole_after_normalising_not_by_prefix_or_pattern(offline, monkeypatch):
    live = Live("tvmaze")
    serve(monkeypatch, live)
    for title in ("Under the", "%", "Under the Dome 2", "UNDER   the dome!!"):
        live.lookups = 0
        resolve_base.candidates(show(title))
        assert live.lookups == (0 if title.startswith("UNDER") else 1), title


def test_a_damaged_file_falls_through_to_the_live_provider(tmp_path, offline, monkeypatch):
    (tmp_path / "data" / "tvmaze-shows.sqlite").write_bytes(b"torn" * 100)
    live = Live("tvmaze")
    serve(monkeypatch, live)
    (match,) = resolve_base.candidates(show())
    assert live.lookups == 1 and match.origin == layer.LIVE


def test_manga_goes_to_the_manga_set_and_not_the_anime_one(offline, monkeypatch):
    live = Live("jikan_manga", medium=MediaType.COMIC)
    serve(monkeypatch, live)
    (match,) = resolve_base.candidates(Signals(title="Berserk", medium=MediaType.COMIC))
    assert live.lookups == 0 and match.origin["dataset"] == "LeData/media-metadata-jikan-manga"
    assert match.signals.artist == "Miura, Kentarou"


def test_an_anime_movie_row_is_a_movie(offline, monkeypatch):
    serve(monkeypatch, Live("anilist"))
    (match,) = resolve_base.candidates(show("Cowboy Bebop: The Movie"))
    assert match.signals.medium == MediaType.MOVIE and match.external_ids.anilist_id == 5


# -- stand-alone sets --------------------------------------------------------------------

def test_a_standalone_set_adds_candidates_beside_the_live_ones(offline, monkeypatch):
    live = Live("steam_shop", medium=MediaType.GAME)
    serve(monkeypatch, live)
    matches = resolve_base.candidates(Signals(title="Counter-Strike: Global Offensive", medium=MediaType.GAME))
    assert {m.provider for m in matches} == {"steam_shop", "ledata"}
    mine = next(m for m in matches if m.provider == "ledata")
    assert mine.external_ids.extra == {"steam_appid": "730"}
    assert mine.signals.artist == "Valve" and mine.signals.year == 2012
    assert mine.origin["dataset"] == "LeData/media-metadata-steam-games"


def test_an_artist_is_searched_by_name_only_when_no_title_is_given(offline, monkeypatch):
    serve(monkeypatch)
    (match,) = resolve_base.candidates(Signals(artist="johann sebastian BACH", medium=MediaType.MUSIC))
    assert match.provider == "ledata"
    assert match.external_ids.musicbrainz_artist == "24f1766e-9635-4d58-a4d4-9413f9f98a4c"
    assert resolve_base.candidates(Signals(title="Air", artist="Johann Sebastian Bach", medium=MediaType.MUSIC)) == []


def test_standalone_sets_are_not_served_for_an_unset_medium_and_not_when_the_layer_is_off(offline, monkeypatch):
    serve(monkeypatch)
    assert resolve_base.candidates(Signals(title="Counter-Strike: Global Offensive")) == []
    layer.configure(OfflineConfig())
    assert resolve_base.candidates(Signals(title="Counter-Strike: Global Offensive", medium=MediaType.GAME)) == []


def test_a_standalone_set_is_served_at_any_age_since_nothing_live_competes(offline, monkeypatch):
    serve(monkeypatch)
    offline.now = BUILT_AT + 10 * MAX_AGE
    assert len(resolve_base.candidates(Signals(title="Counter-Strike: Global Offensive", medium=MediaType.GAME))) == 1


# -- enrichment --------------------------------------------------------------------------

def test_enrich_is_answered_offline_before_the_provider(offline, monkeypatch):
    live = Live("tvmaze", enriches=ExternalIds(imdb="ttLIVE"))
    serve(monkeypatch, live)
    out = resolve_base.enrich(ExternalIds(tvdb=264492), apply_maps=False)
    assert live.enrichments == 0
    assert out.imdb == "tt1553656" and out.tvmaze == 1


def test_enrich_miss_refresh_and_stale_ask_the_provider(offline, monkeypatch):
    live = Live("tvmaze", enriches=ExternalIds(imdb="ttLIVE"))
    serve(monkeypatch, live)
    assert resolve_base.enrich(ExternalIds(tvdb=1), apply_maps=False).imdb == "ttLIVE"
    assert live.enrichments == 1
    with bypass_cache(True):
        assert resolve_base.enrich(ExternalIds(tvdb=264492), apply_maps=False).imdb == "ttLIVE"
    assert live.enrichments == 2
    offline.now = BUILT_AT + MAX_AGE + 1
    _cache.cache().clear()
    assert resolve_base.enrich(ExternalIds(tvdb=264492), apply_maps=False).imdb == "ttLIVE"
    assert live.enrichments == 3


def test_a_provider_with_nothing_to_enrich_is_not_answered_for(offline, monkeypatch):
    serve(monkeypatch, LiveWithoutEnrich("tvmaze"))
    assert resolve_base.enrich(ExternalIds(tvdb=264492), apply_maps=False).imdb is None


def test_a_standalone_set_fills_cross_references_after_the_live_ones(offline, monkeypatch):
    serve(monkeypatch)
    out = resolve_base.enrich(ExternalIds(musicbrainz_artist="24f1766e-9635-4d58-a4d4-9413f9f98a4c"),
                              apply_maps=False)
    assert out.audiodb_artist_id == 114265 and out.metal_archives_band == 3540442600
    assert out.bandcamp_band_id == 42 and out.extra["progarchives_id"] == "7"
    assert out.soundcloud_user_id == "sc-9"


class Spy:
    """Counts the queries that reach the store."""

    def __init__(self, monkeypatch):
        self.queries = []
        real = Store._query

        def spy(store, name, sql, params):
            self.queries.append(params)
            return real(store, name, sql, params)

        monkeypatch.setattr(Store, "_query", spy)


HOSTILE_IDS = [ExternalIds(isbn_10="12'; DROP TABLE item;--"), ExternalIds(isbn_13="9781577658214' OR '1'='1"),
               ExternalIds(olid="OL1W' OR 1=1"), ExternalIds(musicbrainz_artist="x' OR '1'='1"),
               ExternalIds(musicbrainz_artist="24f1766e-9635-4d58-a4d4-9413f9f98a4c'")]


@pytest.mark.parametrize("ids", HOSTILE_IDS, ids=lambda i: str(i.model_dump(exclude_none=True)))
def test_an_id_that_fails_the_existing_rules_never_reaches_sql(offline, monkeypatch, ids):
    spy = Spy(monkeypatch)
    live = Live("openlibrary", medium=MediaType.BOOK, enriches=ExternalIds(olid="OL9W"))
    serve(monkeypatch, live)
    out = resolve_base.enrich(ids, apply_maps=False)
    assert spy.queries == []
    assert out.model_dump(exclude_none=True, exclude={"extra"}) == {
        **ids.model_dump(exclude_none=True, exclude={"extra"}),
        **({"olid": "OL9W"} if not ids.olid else {})}


def test_an_isbn_with_hyphens_is_looked_up_as_digits(offline, monkeypatch):
    live = Live("openlibrary", medium=MediaType.BOOK, enriches=ExternalIds(olid="OL9W"))
    serve(monkeypatch, live)
    out = resolve_base.enrich(ExternalIds(isbn_13="978-1-57765-821-4"), apply_maps=False)
    assert live.enrichments == 0 and out.olid == "OL8193416W"


# -- catalogue lookup --------------------------------------------------------------------

class FakeSource(catalog_base.CatalogSource):
    lookup_kinds = {"series": ("tvmaze", "tvdb", "imdb", "anilist", "mal"), "book": ("openlibrary", "isbn"),
                    "movie": ("anilist", "mal")}
    children_kinds = frozenset({"series"})

    def __init__(self, name="tvmaze"):
        self.name, self.calls = name, 0

    def available(self):
        return True

    def lookup(self, scheme, value, kind, *, children, timeout):
        self.calls += 1
        return Item(kind=kind, title=f"live:{value}")


@pytest.fixture
def live_source(monkeypatch, offline):
    source = FakeSource()
    monkeypatch.setattr(catalog_base, "_SOURCES", {"tvmaze": source})
    return source


def test_lookup_without_children_is_answered_offline(offline, live_source):
    answer = catalog.ask("lookup", "tvmaze", "1", "series", children=False)
    assert live_source.calls == 0
    assert answer.providers == ["ledata"] and answer.asked == ["ledata"] and answer.errors == []
    item = answer.value
    assert (item.kind, item.title, item.year, item.release_date) == ("series", "Under the Dome", 2013, "2013-06-24")
    assert item.runtime_min == 60 and item.overview == "A small town."
    assert item.ext_ids == {"tvmaze": "1", "imdb": "tt1553656", "tvdb": "264492"}
    assert item.extra["network_name"] == "CBS" and item.extra["tvrage_id"] == "25988"
    assert answer.origin["dataset"] == "LeData/media-metadata-tvmaze-shows"
    assert answer.origin["revision"] == "rev-tvmaze-shows"


@pytest.mark.parametrize("scheme,value", [("tvdb", "264492"), ("imdb", "tt1553656")])
def test_lookup_by_any_id_the_set_holds(offline, live_source, scheme, value):
    assert catalog.ask("lookup", scheme, value, "series", children=False).value.title == "Under the Dome"


def test_lookup_with_children_goes_live_because_a_row_has_none(offline, live_source):
    answer = catalog.ask("lookup", "tvmaze", "1", "series", children=True)
    assert live_source.calls == 1 and answer.value.title == "live:1" and answer.origin == layer.LIVE


def test_lookup_miss_refresh_stale_and_a_named_provider_go_live(offline, live_source):
    catalog.ask("lookup", "tvmaze", "424242", "series", children=False)
    assert live_source.calls == 1
    answer = catalog.ask("lookup", "tvmaze", "1", "series", children=False, refresh=True)
    assert live_source.calls == 2 and answer.origin == layer.LIVE
    catalog.ask("lookup", "tvmaze", "1", "series", children=False, provider="tvmaze")
    assert live_source.calls == 3
    offline.now = BUILT_AT + MAX_AGE + 1
    catalog.reset_cache()
    catalog.ask("lookup", "tvmaze", "1", "series", children=False)
    assert live_source.calls == 4


def test_lookup_with_the_layer_off_reports_no_origin(tmp_path, offline, live_source):
    layer.configure(OfflineConfig())
    answer = catalog.ask("lookup", "tvmaze", "1", "series", children=False)
    assert live_source.calls == 1 and answer.origin is None


def test_a_cached_live_answer_does_not_hide_a_fresh_offline_one(offline, live_source):
    config = layer._layer()[0]
    layer.configure(OfflineConfig())
    assert catalog.ask("lookup", "tvmaze", "1", "series", children=False).value.title == "live:1"
    layer.configure(config, clock=lambda: Clock.now)
    assert catalog.ask("lookup", "tvmaze", "1", "series", children=False).value.title == "Under the Dome"


def test_a_book_is_found_by_isbn_with_or_without_hyphens(offline, monkeypatch):
    monkeypatch.setattr(catalog_base, "_SOURCES", {"openlibrary": FakeSource("openlibrary")})
    for isbn in ("9781577658214", "978-1-57765-821-4", "066577981X", "0-66577-981-x"):
        answer = catalog.ask("lookup", "isbn", isbn, "book")
        assert answer.value.title == "The Picture of Dorian Gray", isbn
        assert answer.value.ext_ids["openlibrary"] == "OL8193416W"
        assert answer.origin["source"] == "offline"


def test_an_isbn_that_is_not_one_is_not_looked_up_offline(offline, monkeypatch):
    source = FakeSource("openlibrary")
    monkeypatch.setattr(catalog_base, "_SOURCES", {"openlibrary": source})
    spy = Spy(monkeypatch)
    answer = catalog.ask("lookup", "isbn", "9781577658214' OR '1'='1", "book")
    assert spy.queries == [] and source.calls == 1 and answer.origin == layer.LIVE


def test_an_anime_lookup_answers_with_the_kind_the_row_records(offline, monkeypatch):
    monkeypatch.setattr(catalog_base, "_SOURCES", {"anilist": FakeSource("anilist")})
    answer = catalog.ask("lookup", "anilist", "5")
    assert (answer.value.kind, answer.value.title, answer.value.ext_ids["mal"]) == ("movie", "Cowboy Bebop: The Movie", "5")


@pytest.mark.parametrize("scheme,value,kind", [("tvmaze", "1 OR 1=1", "series"), ("imdb", "tt1553656'--", "series"),
                                               ("tvdb", "264492; DROP TABLE item", "series")])
def test_malformed_ids_are_rejected_by_the_existing_checks(offline, live_source, scheme, value, kind):
    with pytest.raises(catalog.InvalidId):
        catalog.ask("lookup", scheme, value, kind, children=False)
    assert live_source.calls == 0
