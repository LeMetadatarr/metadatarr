# SPDX-License-Identifier: Apache-2.0
"""GET /api/v1/extras and GET /api/v1/variants, their capabilities in
/providers, and the variants of the versioned resolve. Offline: the catalogue
sources answer from the placeholder fixtures under ``tests/fixtures/catalog``
(the shapes of TMDB's videos, Radarr's proxy, a Discogs release and an IFDB
search page, with made-up values), and fanedit.org from a fake session."""
from __future__ import annotations

import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from pyfanedit import FaneditClient  # noqa: E402

from metadatarr import catalog  # noqa: E402
from metadatarr.catalog import _http  # noqa: E402
from metadatarr.catalog.shapes import extra_type  # noqa: E402
from metadatarr.resolve.base import all_providers  # noqa: E402
from metadatarr.server.app import create_app  # noqa: E402
from tests._catalog_fixtures import FIXTURES, boom, ok  # noqa: E402
from tests.test_catalog_sources import RADARR, TMDB, recorded  # noqa: E402

DISCOGS = "https://api.discogs.com"
EXTRA_FIELDS = {"type", "type_raw", "title", "site", "key", "url", "language", "country", "official", "resolution",
                "runtime_s", "published"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for var in ("METADATARR_API_KEYS", "METADATARR_AUTH_EXEMPT", "METADATARR_RATE_LIMIT", "METADATARR_HTTP_CACHE",
                "METADATARR_CATALOG_CACHE_TTL", "METADATARR_CATALOG_CACHE_SIZE", "TMDB_API_KEY", "DISCOGS_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    catalog.reset_cache()
    yield
    catalog.reset_cache()


@pytest.fixture
def replay(monkeypatch):
    r = recorded()
    r.add("GET", f"{TMDB}/movie/603/videos", ok("tmdb_movie_603_videos.json"))
    r.add("GET", f"{TMDB}/tv/1396/videos", ok("tmdb_tv_1396_videos.json"))
    r.add("GET", f"{TMDB}/tv/1396/season/1/videos", ok("tmdb_tv_1396_season_1_videos.json"))
    r.add("GET", f"{TMDB}/find/81189", ok("tmdb_find_tvdb_81189.json"), {"external_source": "tvdb_id"})
    r.add("GET", f"{RADARR}/movie/900001", ok("radarr_movie_900001.json"))
    r.add("GET", f"{DISCOGS}/releases/249504", ok("discogs_release_249504.json"))
    monkeypatch.setattr(_http, "send", r)
    return r


def client() -> TestClient:
    return TestClient(create_app())


# -- extras ---------------------------------------------------------------------

def test_tmdb_videos_answer_extras_in_the_published_shape(replay, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "k")
    r = client().get("/api/v1/extras", params={"scheme": "tmdb", "value": "603", "kind": "movie"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"provider", "extras", "providers", "errors", "truncated"}
    assert body["provider"] == "tmdb" and body["providers"] == ["tmdb"] and body["errors"] == []
    trailer, bts, bloopers = body["extras"]
    assert set(trailer) == EXTRA_FIELDS
    assert trailer == {"type": "trailer", "type_raw": "Trailer", "title": "Placeholder Official Trailer",
                       "site": "youtube", "key": "plcHldr0001", "url": "https://www.youtube.com/watch?v=plcHldr0001",
                       "language": "en", "country": "US", "official": True, "resolution": 1080, "runtime_s": None,
                       "published": "2001-02-03"}
    assert (bts["type"], bts["type_raw"], bts["url"], bts["official"], bts["resolution"]) == (
        "behind-the-scenes", "Behind the Scenes", "https://vimeo.com/100000001", False, 720)
    assert (bloopers["type"], bloopers["type_raw"], bloopers["language"]) == ("other", "Bloopers", "de")
    assert not any(c.startswith(f"GET {RADARR}") for c in replay.calls), "TMDB answers extras before the proxy"


def test_series_and_season_extras_by_tvdb_go_through_tmdb_find(replay, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "k")
    c = client()
    series = c.get("/api/v1/extras", params={"scheme": "tvdb", "value": "81189", "kind": "series"}).json()
    assert [(e["type"], e["key"]) for e in series["extras"]] == [("teaser", "plcHldr0004")]
    season = c.get("/api/v1/extras", params={"scheme": "tvdb", "value": "81189/1", "kind": "season"}).json()
    assert [(e["type"], e["key"]) for e in season["extras"]] == [("trailer", "plcHldr0005")]
    by_tmdb = c.get("/api/v1/extras", params={"scheme": "tmdb", "value": "1396/1", "kind": "season"}).json()
    assert by_tmdb["extras"] == season["extras"]


def test_without_tmdb_a_movie_gets_the_proxy_trailer(replay):
    r = client().get("/api/v1/extras", params={"scheme": "tmdb", "value": "900001", "kind": "movie"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "skyhook"
    assert body["extras"] == [{"type": "trailer", "type_raw": "YouTubeTrailerId",
                               "title": "Placeholder Movie (2001) Trailer", "site": "youtube", "key": "plcHldr0008",
                               "url": "https://www.youtube.com/watch?v=plcHldr0008", "language": "", "country": "",
                               "official": None, "resolution": None, "runtime_s": None, "published": None}]


def test_a_movie_the_proxy_names_no_trailer_for_has_no_extras(replay):
    body = client().get("/api/v1/extras", params={"scheme": "tmdb", "value": "603"}).json()
    assert body["provider"] == "skyhook" and body["extras"] == []


def test_failing_tmdb_falls_back_to_the_proxy_and_is_listed(replay, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "k")
    replay.add("GET", f"{TMDB}/movie/900001/videos", boom("connection reset"))
    r = client().get("/api/v1/extras", params={"scheme": "tmdb", "value": "900001", "kind": "movie"})
    body = r.json()
    assert body["provider"] == "skyhook" and [e["key"] for e in body["extras"]] == ["plcHldr0008"]
    assert [(e["provider"], e["error_type"]) for e in body["errors"]] == [("tmdb", "ConnectionError")]
    assert r.headers["cache-control"] == "no-cache"


def test_discogs_release_videos_are_album_extras(replay):
    r = client().get("/api/v1/extras", params={"scheme": "discogs", "value": "249504", "kind": "album"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "discogs"
    first, live = body["extras"]
    assert (first["type"], first["site"], first["key"], first["runtime_s"], first["official"]) == (
        "music-video", "youtube", "plcHldr0006", 213.0, None)
    assert first["url"] == "https://www.youtube.com/watch?v=plcHldr0006"
    assert live["runtime_s"] is None


@pytest.mark.parametrize("params,provider", [
    ({"scheme": "tvdb", "value": "81189", "kind": "series"}, None),        # TMDB without its key
    ({"scheme": "tmdb", "value": "1396/1", "kind": "season"}, None),
    ({"scheme": "musicbrainz", "value": "x", "kind": "album"}, None),
    ({"scheme": "tmdb", "value": "603", "kind": "movie", "provider": "tmdb"}, "tmdb"),
    ({"scheme": "tmdb", "value": "603", "kind": "movie", "provider": "tvmaze"}, "tvmaze"),
])
def test_extras_nobody_can_answer_are_501(replay, params, provider):
    r = client().get("/api/v1/extras", params=params)
    assert r.status_code == 501, r.text
    body = r.json()
    assert body["error"] == "not supported" and body["provider"] == provider and body["message"]
    assert replay.calls == []


def test_extras_501_names_the_unavailable_provider(replay):
    r = client().get("/api/v1/extras", params={"scheme": "tvdb", "value": "1", "kind": "series"})
    message = r.json()["message"]
    assert "unavailable: tmdb" in message


def test_extras_of_an_unknown_id_are_404(replay):
    replay.add("GET", f"{RADARR}/movie/1", (404, b"{}"))
    r = client().get("/api/v1/extras", params={"scheme": "tmdb", "value": "1", "kind": "movie"})
    assert r.status_code == 404
    assert r.json() == {"error": "not found", "providers": ["skyhook"], "errors": []}


def test_extra_type_reads_provider_words():
    words = ("Trailer", "Behind the Scenes", "making_of", "Music Video", "Live Performance", "Opening Credits", "",
             None)
    assert [extra_type(w) for w in words] == ["trailer", "behind-the-scenes", "making-of", "music-video",
                                              "live-session", "other", "other", "other"]


# -- capabilities ------------------------------------------------------------------

def test_providers_list_extras_and_variants_capabilities():
    infos = {p["name"]: p["capabilities"] for p in client().get("/api/v1/providers").json()["providers"]}
    assert infos["tmdb"]["extras"] == {"movie": ["tmdb", "imdb"], "season": ["tmdb", "tvdb"],
                                       "series": ["tmdb", "imdb", "tvdb"]}
    assert infos["skyhook"]["extras"] == {"movie": ["tmdb", "imdb"]}
    assert infos["discogs"]["extras"] == {"album": ["discogs"]}
    assert infos["pyfanedit"]["variants"] == {"movie": ["tmdb", "imdb"], "series": ["tvdb", "tmdb", "imdb"]}
    assert all(c["extras"] == {} for n, c in infos.items() if n not in ("tmdb", "skyhook", "discogs"))
    assert all(c["variants"] == {} for n, c in infos.items() if n != "pyfanedit")


def test_extras_and_variants_capabilities_match_what_the_dispatcher_routes():
    for name, source in catalog.all_sources().items():
        for method, table in (("extras", source.extras_kinds), ("variants", source.variants_kinds)):
            for kind, schemes in table.items():
                assert kind in catalog.KINDS, (name, kind)
                for scheme in schemes:
                    assert source.can(method, scheme, kind), (name, method, kind, scheme)


# -- variants ---------------------------------------------------------------------

class _Page:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text, self.status_code = text, status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"fanedit.org answered HTTP {self.status_code}")


class _FanEditOrg:
    """A fake fanedit.org: a search answers the recorded page with its film
    renamed to the title searched for, or ``status``."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.searches = []

    def get(self, url, params=None, headers=None):
        keywords = (params or {}).get("keywords") or ""
        self.searches.append(keywords)
        page = (FIXTURES / "ifdb_search_placeholder.html").read_text().replace("Placeholder Film", keywords)
        return _Page(page, self.status)


@pytest.fixture
def ifdb(monkeypatch):
    site = _FanEditOrg()
    monkeypatch.setattr(all_providers()["pyfanedit"], "_client", FaneditClient(session_factory=lambda: site))
    return site


def _variants(params) -> "tuple[int, dict]":
    r = client().get("/api/v1/variants", params=params)
    return r.status_code, r.json()


def test_variants_are_items_with_the_edit_fields(replay, ifdb):
    status, body = _variants({"scheme": "tmdb", "value": "603", "kind": "movie", "title": "Placeholder Film",
                              "year": 1999})
    assert status == 200, body
    assert set(body) == {"variants", "providers", "errors", "truncated"} and body["providers"] == ["pyfanedit"]
    assert ifdb.searches == ["Placeholder Film"]
    first, second = body["variants"]
    assert (first["kind"], first["title"], first["runtime_min"], first["overview"], first["poster_url"]) == (
        "movie", "Placeholder Film: First Edit", 105.0, "A placeholder synopsis.",
        "https://fanedit.org/media/placeholder-1.jpg")
    assert (first["release_date"], first["year"]) == ("2010-01", 2010)
    assert first["extra"]["variant"] == {
        "type": "fanedit", "name": "First Edit", "editor": "Placeholder Editor", "version": "", "source_formats": [],
        "released": "January 2010", "url": "https://fanedit.org/placeholder-film-first-edit/", "subtype": "fanfix",
        "of": {"tmdb": "603"}, "running_time": "1h 45m"}
    assert (second["extra"]["variant"]["name"], second["extra"]["variant"]["subtype"]) == ("The Second Cut",
                                                                                          "tv_to_movie")
    assert replay.calls == [], "a question with a title needs no lookup"


def test_variants_carry_the_ifdb_id_when_the_search_gives_one(replay, monkeypatch):
    from pyfanedit.models import FaneditSummary

    provider = all_providers()["pyfanedit"]
    monkeypatch.setattr(provider, "search_title", lambda title: [FaneditSummary(
        title="Placeholder Film: Third Edit", url="https://fanedit.org/x/", fanedit_id=4242,
        original_title="Placeholder Film", fanedit_type="FanMix")])
    status, body = _variants({"scheme": "imdb", "value": "tt0133093", "kind": "movie", "title": "Placeholder Film"})
    assert status == 200 and body["variants"][0]["ext_ids"] == {"ifdb": "4242"}


def test_variants_without_a_title_search_by_the_catalogue_title(replay, ifdb):
    status, body = _variants({"scheme": "tmdb", "value": "603", "kind": "movie"})
    assert status == 200, body
    assert ifdb.searches == ["The Matrix"]
    assert f"GET {RADARR}/movie/603" in replay.calls


def test_a_failed_fanedit_org_search_is_an_error_not_an_empty_list(replay, monkeypatch):
    site = _FanEditOrg(status=503)
    monkeypatch.setattr(all_providers()["pyfanedit"], "_client", FaneditClient(session_factory=lambda: site))
    c = client()
    params = {"scheme": "tmdb", "value": "603", "kind": "movie", "title": "Placeholder Film"}
    r = c.get("/api/v1/variants", params=params)
    assert r.status_code == 502, r.text
    body = r.json()
    assert body["error"] == "upstream failed"
    assert [(e["provider"], e["stage"]) for e in body["errors"]] == [("pyfanedit", "variants")]
    assert "503" in body["errors"][0]["message"]
    site.status = 200
    again = c.get("/api/v1/variants", params=params)
    assert again.status_code == 200 and len(again.json()["variants"]) == 2, "a failure must not be cached"


def test_variants_of_an_unknown_id_without_a_title_are_404(replay, ifdb):
    replay.add("GET", f"{RADARR}/movie/1", (404, b"{}"))
    status, body = _variants({"scheme": "tmdb", "value": "1", "kind": "movie"})
    assert status == 404 and body["error"] == "not found"
    assert ifdb.searches == []


@pytest.mark.parametrize("params,provider", [
    ({"scheme": "tvmaze", "value": "1", "kind": "series", "title": "x"}, None),
    ({"scheme": "tmdb", "value": "1", "kind": "album", "title": "x"}, None),
    ({"scheme": "tmdb", "value": "603", "kind": "movie", "title": "x", "provider": "skyhook"}, "skyhook"),
    ({"scheme": "tvmaze", "value": "1", "kind": "series"}, None),
])
def test_variants_nobody_can_answer_are_501(replay, ifdb, params, provider):
    status, body = _variants(params)
    assert status == 501, body
    assert body["error"] == "not supported" and body["provider"] == provider
    assert replay.calls == [] and ifdb.searches == []


def test_variants_by_an_id_no_provider_looks_up_need_a_title(replay, ifdb):
    status, body = _variants({"scheme": "tmdb", "value": "1396", "kind": "series"})
    assert status == 501 and body["message"].startswith("title is required")
    assert ifdb.searches == []


def test_routes_are_in_the_openapi_schema():
    paths = client().get("/openapi.json").json()["paths"]
    assert {"/api/v1/extras", "/api/v1/variants"} <= set(paths)


def test_the_year_drops_edits_released_before_the_film(replay, ifdb):
    base = {"scheme": "tmdb", "value": "603", "kind": "movie", "title": "Placeholder Film"}
    old = _variants({**base, "year": 1984})[1]["variants"]
    remake = _variants({**base, "year": 2021})[1]["variants"]
    assert [v["extra"]["variant"]["name"] for v in old] == ["First Edit", "The Second Cut"]
    assert [v["extra"]["variant"]["name"] for v in remake] == ["The Second Cut"], \
        "the 2010 edit predates a 2021 film; the edit with no release date stays"


def test_the_year_allows_one_year_of_slack(replay, ifdb):
    base = {"scheme": "tmdb", "value": "603", "kind": "movie", "title": "Placeholder Film"}
    assert len(_variants({**base, "year": 2011})[1]["variants"]) == 2
    assert len(_variants({**base, "year": 2012})[1]["variants"]) == 1


@pytest.fixture
def dated_edits(monkeypatch):
    from pyfanedit.models import FaneditSummary

    def edit(name, released, **kw):
        return FaneditSummary(title=f"Placeholder Film: {name}", url=f"https://fanedit.org/{name}/",
                              original_title="Placeholder Film", fanedit_type="FanMix", release_date=released, **kw)

    monkeypatch.setattr(all_providers()["pyfanedit"], "search_title", lambda title: [
        edit("Month", "April 2026"), edit("Bare", "2026"), edit("Iso", "2026-04-02"), edit("Old", "March 2001"),
        edit("Garbled", "sometime soon")])


@pytest.mark.parametrize("year,kept", [
    (2026, ["Month", "Bare", "Iso", "Garbled"]),
    (2030, ["Garbled"]),
])
def test_the_year_filter_reads_every_ifdb_date_format(replay, dated_edits, year, kept):
    status, body = _variants({"scheme": "tmdb", "value": "603", "kind": "movie", "title": "Placeholder Film",
                              "year": year})
    assert status == 200, body
    assert [v["extra"]["variant"]["name"] for v in body["variants"]] == kept


def test_variant_items_carry_the_release_date_and_year(replay, dated_edits):
    body = _variants({"scheme": "tmdb", "value": "603", "kind": "movie", "title": "Placeholder Film"})[1]
    assert [(v["extra"]["variant"]["name"], v["release_date"], v["year"]) for v in body["variants"]] == [
        ("Month", "2026-04", 2026), ("Bare", "2026", 2026), ("Iso", "2026-04-02", 2026),
        ("Old", "2001-03", 2001), ("Garbled", None, None)]


def test_the_title_is_part_of_the_cache_key(replay, ifdb):
    base = {"scheme": "tmdb", "value": "603", "kind": "movie"}
    _variants({**base, "title": "Placeholder Film"})
    _variants({**base, "title": "Another Film"})
    assert ifdb.searches == ["Placeholder Film", "Another Film"]


def test_a_title_longer_than_the_value_cap_is_422_and_not_searched(replay, ifdb):
    status, body = _variants({"scheme": "tmdb", "value": "603", "kind": "movie", "title": "x" * 60000})
    assert status == 422 and "title is longer than 200" in body["message"]
    assert ifdb.searches == []
    status, _ = _variants({"scheme": "tmdb", "value": "603", "kind": "movie", "title": "x" * 200})
    assert status == 200 and ifdb.searches == ["x" * 200]


def test_a_long_catalogue_title_is_not_capped(replay, ifdb):
    movie = json.loads((FIXTURES / "radarr_movie_603.json").read_text())
    movie["Title"] = "x" * 201
    replay.add("GET", f"{RADARR}/movie/604", (200, movie))
    status, body = _variants({"scheme": "tmdb", "value": "604", "kind": "movie"})
    assert status == 200, body
    assert ifdb.searches == ["x" * 201]


def test_a_failed_catalogue_title_lookup_is_502(replay, ifdb):
    replay.add("GET", f"{RADARR}/movie/605", (503, b"{}"))
    status, body = _variants({"scheme": "tmdb", "value": "605", "kind": "movie"})
    assert status == 502 and body["error"] == "upstream failed"
    assert body["providers"] and body["errors"]
    assert ifdb.searches == []


def test_tmdb_videos_without_a_key_are_not_extras(replay, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "k")
    replay.add("GET", f"{TMDB}/movie/777/videos", (200, {"results": [
        {"name": "No key", "site": "YouTube", "type": "Trailer"},
        {"name": "Empty key", "key": "", "site": "YouTube", "type": "Trailer"},
        {"name": "Keyed", "key": "plcHldr0009", "site": "YouTube", "type": "Teaser"}]}))
    body = client().get("/api/v1/extras", params={"scheme": "tmdb", "value": "777", "kind": "movie"}).json()
    assert [e["key"] for e in body["extras"]] == ["plcHldr0009"]


# -- variants on the versioned resolve ------------------------------------------------

def test_versioned_resolve_by_id_collects_variants(replay, ifdb):
    r = client().post("/api/v1/resolve", json={"ids": {"tmdb": "603"}, "kind": "movie", "include_variants": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["match"]["item"]["title"] == "The Matrix"
    assert ifdb.searches == ["The Matrix"]
    names = [v["name"] for v in body["variants"]]
    assert names == ["The Matrix: First Edit", "The Matrix - The Second Cut"]
    extra = body["variants"][0]["external_ids"]["extra"]
    assert extra["faneditor"] == "Placeholder Editor" and extra["running_time"] == "1h 45m"
    assert extra["fanedit_release_date"] == "January 2010" and extra["synopsis"] == "A placeholder synopsis."
    assert extra["cover_url"] == "https://fanedit.org/media/placeholder-1.jpg" and extra["edit_name"] == "First Edit"
    assert body["variants"][0]["external_ids"]["derived_from_imdb"] == "tt0133093"


def test_versioned_resolve_reports_a_failed_variants_search(replay, monkeypatch):
    site = _FanEditOrg(status=503)
    monkeypatch.setattr(all_providers()["pyfanedit"], "_client", FaneditClient(session_factory=lambda: site))
    body = client().post("/api/v1/resolve", json={"ids": {"tmdb": "603"}, "kind": "movie",
                                                  "include_variants": True}).json()
    assert body["variants"] == []
    assert [(e["provider"], e["stage"]) for e in body["errors"]] == [("pyfanedit", "variants")]
    assert [(e["provider"], e["stage"]) for e in body["provider_errors"]] == [("pyfanedit", "variants")]


def test_versioned_resolve_without_include_variants_does_not_search(replay, ifdb):
    body = client().post("/api/v1/resolve", json={"ids": {"tmdb": "603"}, "kind": "movie"}).json()
    assert body["match"]["item"]["title"] == "The Matrix" and body["variants"] == []
    assert ifdb.searches == []


def test_a_client_year_survives_the_title_lookup(replay, ifdb):
    status, body = _variants({"scheme": "tmdb", "value": "603", "kind": "movie", "year": 2030})
    assert status == 200, body
    assert ifdb.searches == ["The Matrix"]
    assert [v["extra"]["variant"]["name"] for v in body["variants"]] == ["The Second Cut"], \
        "year 2030 from the client, not the catalogue's, filters the edits"


@pytest.mark.parametrize("value", ["\u0662\u0664\u0669\u0665\u0660\u0664", "\u00b2", "24950\u00b2", "abc", "-1", "0"])
def test_a_discogs_id_must_be_ascii_digits(replay, value):
    r = client().get("/api/v1/extras", params={"scheme": "discogs", "value": value, "kind": "album"})
    assert r.status_code == 422, r.text
