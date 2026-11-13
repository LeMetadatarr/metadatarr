# SPDX-License-Identifier: Apache-2.0
"""The catalogue routes over HTTP (/api/v1/lookup, /credits, /person), the
id-aware POST /api/v1/resolve and the provider capabilities. Offline: the
real sources answer from recorded fixtures, the resolver from stubs."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from mediavocab import MediaType  # noqa: E402
from mediavocab.models import ExternalIds  # noqa: E402
from mediavocab.models.signals import Signals  # noqa: E402

from metadatarr import catalog  # noqa: E402
from metadatarr.catalog import _http, base as catalog_base  # noqa: E402
from metadatarr.catalog.shapes import Item  # noqa: E402
from metadatarr.resolve import base as resolve_base  # noqa: E402
from metadatarr.resolve.base import MetadataProvider, ProviderMatch  # noqa: E402
from metadatarr.server.app import create_app  # noqa: E402
from metadatarr.server.config import ServerConfig  # noqa: E402
from tests._catalog_fixtures import boom  # noqa: E402
from tests.test_catalog_sources import recorded  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for var in ("METADATARR_API_KEYS", "METADATARR_AUTH_EXEMPT", "METADATARR_RATE_LIMIT", "METADATARR_HTTP_CACHE",
                "METADATARR_CATALOG_CACHE_TTL", "METADATARR_CATALOG_CACHE_SIZE", "TMDB_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    catalog.reset_cache()
    yield
    catalog.reset_cache()


@pytest.fixture
def replay(monkeypatch):
    r = recorded()
    monkeypatch.setattr(_http, "send", r)
    return r


def client(config: Optional[ServerConfig] = None) -> TestClient:
    return TestClient(create_app(config or ServerConfig()))


# -- lookup / credits / person -------------------------------------------------------

def test_lookup_answers_item_with_children_providers_and_cache_headers(replay):
    r = client().get("/api/v1/lookup", params={"scheme": "tvdb", "value": "81189", "kind": "series"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"item", "providers", "errors", "truncated"}
    assert body["providers"] == ["skyhook"] and body["errors"] == []
    item = body["item"]
    assert set(item) == {"kind", "title", "sort_title", "original_title", "year", "release_date", "runtime_min",
                         "overview", "poster_url", "position", "ext_ids", "extra", "children"}
    assert item["title"] == "Breaking Bad" and [c["kind"] for c in item["children"]] == ["season"] * 3
    assert r.headers["cache-control"] == "public, max-age=3600"
    assert r.headers["etag"].startswith('"')


def test_lookup_conditional_get_is_304(replay):
    c = client()
    params = {"scheme": "tmdb", "value": "603"}
    etag = c.get("/api/v1/lookup", params=params).headers["etag"]
    again = c.get("/api/v1/lookup", params=params, headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""


def test_lookup_is_cached_and_refresh_asks_the_catalogue_again(replay):
    c = client()
    params = {"scheme": "tmdb", "value": "603", "kind": "movie"}
    c.get("/api/v1/lookup", params=params)
    c.get("/api/v1/lookup", params=params)
    assert replay.calls.count("GET https://radarrapi.servarr.com/v1/movie/603") == 1
    c.get("/api/v1/lookup", params={**params, "refresh": "1"})
    assert replay.calls.count("GET https://radarrapi.servarr.com/v1/movie/603") == 2


def test_cache_ttl_setting_reaches_the_header(replay, monkeypatch):
    monkeypatch.setenv("METADATARR_CATALOG_CACHE_TTL", "120")
    catalog.reset_cache()
    r = client().get("/api/v1/lookup", params={"scheme": "tmdb", "value": "603"})
    assert r.headers["cache-control"] == "public, max-age=120"


def test_credits_route_answers_vocabulary_roles(replay):
    r = client().get("/api/v1/credits", params={"scheme": "anilist", "value": "1", "kind": "series"})
    assert r.status_code == 200
    body = r.json()
    assert body["providers"] == ["anilist"]
    first = body["credits"][0]
    assert set(first) == {"person", "role", "character", "position", "note", "item"}
    assert set(first["person"]) == {"name", "kind", "ext_ids", "aliases", "image_url", "sort_name", "birth_date",
                                    "death_date", "country", "bio", "extra"}
    assert (first["role"], first["character"], first["position"]) == ("voice-actor", "Spike Spiegel", 0)


def test_person_route_answers_person_and_filmography(replay):
    r = client().get("/api/v1/person", params={"scheme": "musicbrainz", "value": "a74b1b7f-71a5-4011-9441-d0b5e4122711"})
    assert r.status_code == 200
    body = r.json()
    assert body["person"]["kind"] == "group" and body["credits"][0]["item"]["kind"] == "album"
    assert body["providers"] == ["musicbrainz"]


def test_unknown_id_is_404_and_not_cacheable(replay):
    replay.add("GET", "https://radarrapi.servarr.com/v1/movie/1", (404, b"{}"))
    r = client().get("/api/v1/lookup", params={"scheme": "tmdb", "value": "1", "kind": "movie"})
    assert r.status_code == 404
    assert r.json() == {"error": "not found", "providers": ["skyhook"], "errors": []}
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path,params,provider", [
    ("/api/v1/lookup", {"scheme": "tmdb", "value": "603", "kind": "track"}, None),
    ("/api/v1/credits", {"scheme": "musicbrainz", "value": "a74b1b7f-71a5-4011-9441-d0b5e4122711", "kind": "artist"}, None),
    ("/api/v1/person", {"scheme": "tvdb", "value": "1"}, None),
    ("/api/v1/person", {"scheme": "tmdb", "value": "1"}, None),  # TMDB without its key
    ("/api/v1/lookup", {"scheme": "tmdb", "value": "603", "kind": "movie", "provider": "bandcamp"}, "bandcamp"),
    ("/api/v1/credits", {"scheme": "anilist", "value": "1", "kind": "series", "provider": "skyhook"}, "skyhook"),
])
def test_questions_nobody_can_answer_are_501_never_an_empty_200(replay, path, params, provider):
    r = client().get(path, params=params)
    assert r.status_code == 501, r.text
    body = r.json()
    assert body["error"] == "not supported" and body["provider"] == provider and body["message"]
    assert replay.calls == []


def test_every_asked_provider_failing_is_502_with_errors(replay):
    replay.add("GET", "https://radarrapi.servarr.com/v1/movie/603", boom("connection reset"))
    r = client().get("/api/v1/lookup", params={"scheme": "tmdb", "value": "603"})
    assert r.status_code == 502
    body = r.json()
    assert body["error"] == "upstream failed"
    assert [(e["provider"], e["error_type"]) for e in body["errors"]] == [("skyhook", "ConnectionError")]


def test_a_failing_provider_does_not_fail_the_request(replay, monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "k")
    replay.add("GET", "https://radarrapi.servarr.com/v1/movie/603", (500, b"oops"))
    r = client().get("/api/v1/lookup", params={"scheme": "tmdb", "value": "603", "kind": "movie"})
    assert r.status_code == 200
    body = r.json()
    assert body["providers"] == ["tmdb"] and body["item"]["title"] == "The Matrix"
    assert [(e["provider"], e["error_type"]) for e in body["errors"]] == [("skyhook", "UpstreamError")]
    assert r.headers["cache-control"] == "no-cache"


def test_bad_kind_is_422(replay):
    r = client().get("/api/v1/lookup", params={"scheme": "tmdb", "value": "603", "kind": "spaceship"})
    assert r.status_code == 422 and r.json()["error"] == "invalid request"


def test_catalogue_routes_honour_api_keys(replay):
    c = client(ServerConfig(api_keys=["s3cret"]))
    params = {"scheme": "tmdb", "value": "603"}
    assert c.get("/api/v1/lookup", params=params).status_code == 401
    ok = c.get("/api/v1/lookup", params=params, headers={"X-Api-Key": "s3cret"})
    assert ok.status_code == 200 and ok.headers["cache-control"].startswith("private")


def test_catalogue_routes_are_versioned_only():
    c = client()
    assert c.get("/lookup", params={"scheme": "tmdb", "value": "1"}).status_code == 404
    paths = c.get("/openapi.json").json()["paths"]
    assert {"/api/v1/lookup", "/api/v1/credits", "/api/v1/person"} <= set(paths)


# -- providers --------------------------------------------------------------------

def test_providers_list_capabilities_for_every_provider():
    for path in ("/api/v1/providers", "/providers"):
        infos = {p["name"]: p for p in client().get(path).json()["providers"]}
        assert all(set(p["capabilities"]) == {"lookup", "children", "credits", "person", "extras", "variants",
                                              "search_kinds"} for p in infos.values())
        sky = infos["skyhook"]["capabilities"]
        assert sky["lookup"]["movie"] == ["tmdb", "imdb"] and "series" in sky["children"]
        assert infos["musicbrainz"]["capabilities"]["person"] == ["musicbrainz"]
        assert infos["bandcamp"]["capabilities"] == {"lookup": {}, "children": [], "credits": {}, "person": [],
                                                     "extras": {}, "variants": {}, "search_kinds": []}


def test_capabilities_match_what_the_dispatcher_routes():
    for name, source in catalog.all_sources().items():
        for kind, schemes in source.lookup_kinds.items():
            for scheme in schemes:
                assert source.can("lookup", scheme, kind), (name, kind, scheme)
        assert set(source.children_kinds) <= set(source.lookup_kinds), name
        assert set(source.children_kinds) <= set(catalog.CHILD_KIND), name


# -- POST /api/v1/resolve ------------------------------------------------------------

class _Catalogue(catalog_base.CatalogSource):
    name = "zz_catalogue"
    lookup_kinds = {"movie": ("tmdb", "imdb")}

    def __init__(self):
        self.calls = []

    def lookup(self, scheme, value, kind, *, children, timeout):
        self.calls.append((scheme, value, kind, children))
        if value in ("603", "tt0133093"):
            return Item(kind="movie", title="The Matrix", year=1999, ext_ids={"tmdb": "603", "imdb": "tt0133093"},
                        children=[Item(kind="movie", title="should not be sent")] if children else [])
        return None


class _Resolver(MetadataProvider):
    """Two candidates for "zzcat heist": one with TMDB 1, one with TMDB 2."""

    name = "zz_cat_resolver"
    media = {MediaType.MOVIE}

    def is_available(self):
        return True

    def lookup(self, signals):
        return None

    def lookup_candidates(self, signals: Signals):
        if not (signals.title or "").startswith("zzcat"):
            return []
        return [ProviderMatch(provider=self.name, confidence=0.6, external_ids=ExternalIds(tmdb_movie=1),
                              signals=Signals(title="zzcat heist", year=2001, medium=MediaType.MOVIE)),
                ProviderMatch(provider=self.name, confidence=0.5, external_ids=ExternalIds(tmdb_movie=2),
                              signals=Signals(title="zzcat heist", year=2001, medium=MediaType.MOVIE))]


@pytest.fixture
def stubs(monkeypatch):
    source = _Catalogue()
    monkeypatch.setattr(catalog_base, "_SOURCES", {source.name: source})
    monkeypatch.setattr(resolve_base, "_REGISTRY", {_Resolver.name: _Resolver()})
    return source


def test_resolve_by_ids_alone_answers_title_and_confidence(stubs):
    r = client().post("/api/v1/resolve", json={"ids": {"imdb": "tt0133093"}, "kind": "movie"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["match"]["item"]["title"] == "The Matrix" and body["match"]["confidence"] == 1.0
    assert body["match"]["item"]["children"] == []
    assert body["match"]["source"] == "zz_catalogue" and body["providers"] == ["zz_catalogue"]
    assert body["signals"]["title"] == "The Matrix" and body["signals"]["medium"] == "movie"
    assert body["external_ids"]["tmdb_movie"] == 603 and body["external_ids"]["imdb"] == "tt0133093"
    assert body["accepted"][0]["provider"] == "zz_catalogue"
    assert stubs.calls == [("imdb", "tt0133093", "movie", False)]


def test_resolve_by_ids_scores_the_title_against_the_catalogue(stubs):
    c = client()
    same = c.post("/api/v1/resolve", json={"title": "The Matrix", "year": 1999, "ids": {"tmdb": "603"}}).json()
    other = c.post("/api/v1/resolve", json={"title": "Paddington", "year": 1999, "ids": {"tmdb": "603"}}).json()
    assert same["match"]["confidence"] == 1.0
    assert other["match"]["item"]["title"] == "The Matrix" and other["match"]["confidence"] < 0.5


def test_resolve_by_ids_halves_confidence_when_ids_contradict(stubs):
    body = client().post("/api/v1/resolve", json={"ids": {"tmdb": "603", "imdb": "tt9999999"}, "kind": "movie"}).json()
    assert body["match"]["confidence"] == 0.5 and body["match"]["id_conflicts"] == ["imdb"]


def test_resolve_by_unknown_scheme_alone_is_501(stubs):
    r = client().post("/api/v1/resolve", json={"ids": {"discogs": "1"}, "kind": "movie"})
    assert r.status_code == 501 and r.json()["error"] == "not supported"


def test_resolve_by_unknown_id_alone_is_404(stubs):
    r = client().post("/api/v1/resolve", json={"ids": {"tmdb": "42"}, "kind": "movie"})
    assert r.status_code == 404 and r.json()["error"] == "not found"


def test_resolve_needs_a_title_or_an_id(stubs):
    assert client().post("/api/v1/resolve", json={"ids": {"tmdb": "  "}}).status_code == 422


def test_title_resolve_is_narrowed_by_ids(stubs):
    c = client()
    plain = c.post("/api/v1/resolve", json={"title": "zzcat heist", "medium": "movie"}).json()
    assert plain["external_ids"]["tmdb_movie"] == 1
    narrowed = c.post("/api/v1/resolve", json={"title": "zzcat heist", "medium": "movie",
                                               "ids": {"tmdb": "2"}, "kind": "movie"}).json()
    assert narrowed["external_ids"]["tmdb_movie"] == 2, "the candidate with another TMDB id must be dropped"
    assert [m["external_ids"]["tmdb_movie"] for m in narrowed["dropped"]] == [1]
    assert narrowed["match"]["confidence"] >= 0.95
    assert narrowed["match"]["item"]["ext_ids"]["tmdb"] == "2"


def test_v1_title_resolve_keeps_the_legacy_answer_as_a_subset(stubs):
    c = client()
    legacy = c.post("/resolve", json={"title": "zzcat heist", "medium": "movie"}).json()
    v1 = c.post("/api/v1/resolve", json={"title": "zzcat heist", "medium": "movie"}).json()
    assert {k: v1[k] for k in legacy} == legacy
    assert {"match", "providers", "errors", "unsupported"} <= set(v1)


def test_legacy_resolve_still_refuses_ids(stubs):
    assert client().post("/resolve", json={"title": "x", "ids": {"tmdb": "1"}}).status_code == 422


def test_out_of_range_id_is_422_invalid_id(replay):
    r = client().get("/api/v1/lookup", params={"scheme": "tmdb", "value": "99999999999999999999"})
    assert r.status_code == 422 and r.json()["error"] == "invalid id"
    assert replay.calls == []


def test_responses_say_whether_they_were_truncated(replay):
    body = client().get("/api/v1/lookup", params={"scheme": "tmdb", "value": "603"}).json()
    assert body["truncated"] is False


def test_resolve_by_edition_id_is_not_a_conflict(replay):
    r = client().post("/api/v1/resolve", json={"ids": {"openlibrary": "OL61027603M"}})
    body = r.json()
    assert r.status_code == 200, r.text
    assert body["match"]["confidence"] == 1.0 and body["match"]["id_conflicts"] == []
    assert body["match"]["item"]["ext_ids"]["openlibrary_edition"] == "OL61027603M"


def test_resolve_by_mal_id_of_a_movie_answers_a_movie(replay):
    replay.add("POST", "https://graphql.anilist.co", lambda **kw: (200, {"data": {"Media": {
        "id": 47, "idMal": 47, "format": "MOVIE", "title": {"romaji": "AKIRA"}, "startDate": {"year": 1988}}}}))
    body = client().post("/api/v1/resolve", json={"ids": {"mal": "47"}}).json()
    assert body["match"]["item"]["kind"] == "movie" and body["signals"]["medium"] == "movie"


def _paged_anilist(pages, root="Media", connection="characters"):
    def run(*, method, url, params, json_body, timeout):
        page = json_body["variables"].get("page", 1)
        edges = [{"role": "MAIN", "node": {"id": page * 100 + i, "name": {"full": f"Char {page}-{i}"}},
                  "voiceActors": [{"id": page * 1000 + i, "name": {"full": f"VA {page}-{i}"}, "languageV2": "Japanese"}]}
                 for i in range(2)]
        media = {"id": 1, "characters": {"pageInfo": {"hasNextPage": page < pages}, "edges": edges},
                 "staff": {"pageInfo": {"hasNextPage": False}, "edges": []}, "studios": {"edges": []}}
        return 200, {"data": {"Media": media}}
    return run


@pytest.mark.parametrize("pages,truncated", [(3, False), (40, True)])
def test_anilist_credits_page_through_and_flag_the_cap(replay, pages, truncated):
    replay.add("POST", "https://graphql.anilist.co", _paged_anilist(pages))
    body = client().get("/api/v1/credits", params={"scheme": "anilist", "value": "1"}).json()
    voice = [c for c in body["credits"] if c["role"] == "voice-actor"]
    assert len(voice) == 2 * min(pages, 10)
    assert body["truncated"] is truncated


def test_anilist_later_page_failure_keeps_the_first_pages(replay):
    pages = _paged_anilist(5)

    def flaky(**kw):
        if kw["json_body"]["variables"]["page"] == 3:
            raise ConnectionError("reset")
        return pages(**kw)
    replay.add("POST", "https://graphql.anilist.co", flaky)
    body = client().get("/api/v1/credits", params={"scheme": "anilist", "value": "1"}).json()
    assert len([c for c in body["credits"] if c["role"] == "voice-actor"]) == 4
    assert body["truncated"] is True and [e["error_type"] for e in body["errors"]] == ["ConnectionError"]


def test_a_failed_later_page_is_an_error_and_is_not_cached(replay):
    pages = _paged_anilist(5)
    calls = []

    def flaky(**kw):
        calls.append(kw["json_body"]["variables"]["page"])
        if kw["json_body"]["variables"]["page"] == 2:
            raise ConnectionError("reset")
        return pages(**kw)
    replay.add("POST", "https://graphql.anilist.co", flaky)
    c = client()
    r = c.get("/api/v1/credits", params={"scheme": "anilist", "value": "1"})
    body = r.json()
    assert body["truncated"] is True
    assert [(e["provider"], e["error_type"]) for e in body["errors"]] == [("anilist", "ConnectionError")]
    assert r.headers["cache-control"] == "no-cache"
    c.get("/api/v1/credits", params={"scheme": "anilist", "value": "1"})
    assert calls == [1, 2, 1, 2], "the partial answer must not be served from the cache"


def test_the_page_limit_alone_stays_cacheable(replay):
    replay.add("POST", "https://graphql.anilist.co", _paged_anilist(40))
    c = client()
    r = c.get("/api/v1/credits", params={"scheme": "anilist", "value": "1"})
    assert r.json()["truncated"] is True and r.json()["errors"] == []
    assert r.headers["cache-control"].startswith("public")


def test_anilist_requests_are_paced_to_its_30_a_minute_limit():
    from metadatarr import transport
    _http._session()
    assert transport._GLOBAL_LIMITER._per_host["graphql.anilist.co"] >= 2.0


def test_paging_stops_within_the_time_budget(replay, monkeypatch):
    import time as _time
    monkeypatch.setenv("METADATARR_CATALOG_TIMEOUT", "1")
    pages = _paged_anilist(40)

    def slow(**kw):
        _time.sleep(0.25)
        return pages(**kw)
    replay.add("POST", "https://graphql.anilist.co", slow)
    body = client().get("/api/v1/credits", params={"scheme": "anilist", "value": "1"}).json()
    voice = [c for c in body["credits"] if c["role"] == "voice-actor"]
    assert 2 <= len(voice) <= 2 * 4 and body["truncated"] is True and body["errors"] == []


def test_a_429_fails_the_page_and_its_retry_after_is_honoured(replay, monkeypatch):
    from metadatarr.catalog.sources import anilist
    now = [1000.0]
    monkeypatch.setattr(anilist, "_clock", lambda: now[0])
    monkeypatch.setattr(anilist, "_BLOCKED_UNTIL", [0.0])
    pages = _paged_anilist(5)
    calls = []

    def limited(**kw):
        page = kw["json_body"]["variables"]["page"]
        calls.append(page)
        if page == 2:
            return 429, b'{"errors":[{"message":"Too Many Requests."}]}', {"Retry-After": "30"}
        return pages(**kw)
    replay.add("POST", "https://graphql.anilist.co", limited)
    c = client()
    body = c.get("/api/v1/credits", params={"scheme": "anilist", "value": "1"}).json()
    assert body["truncated"] is True
    assert [(e["provider"], e["error_type"]) for e in body["errors"]] == [("anilist", "RateLimited")]
    r = c.get("/api/v1/credits", params={"scheme": "anilist", "value": "1"})
    assert r.status_code == 502 and calls == [1, 2], "inside Retry-After no request is sent"
    now[0] += 31
    assert c.get("/api/v1/credits", params={"scheme": "anilist", "value": "1"}).status_code == 200
    assert calls[2:] == [1, 2]


@pytest.mark.parametrize("route", ["lookup", "credits"])
@pytest.mark.parametrize("value", ["tt0133093/../..", "../..", "tt133", "tt01330930000", "0133093", "tt013309\u0663",
                                   "nm0000206"])
def test_an_imdb_title_id_is_validated_before_it_reaches_a_provider(replay, route, value):
    r = client().get(f"/api/v1/{route}", params={"scheme": "imdb", "value": value, "kind": "movie"})
    assert r.status_code == 422, r.text
    assert replay.calls == []


def test_an_imdb_person_id_is_validated_before_it_reaches_a_provider(replay):
    for value in ("nm0000206/../..", "tt0133093", "nm1"):
        r = client().get("/api/v1/person", params={"scheme": "imdb", "value": value})
        assert r.status_code == 422, (value, r.text)


MBID = "a74b1b7f-71a5-4011-9441-d0b5e4122711"
BAD_MBIDS = ["../..", "a/../b", "x#f", "%2e%2e/%2e%2e", "..%2f", "a\\b", "a\r\nb", "a b", "1", "tt0133093",
             MBID + "/../..", MBID[:-1], MBID + "0", MBID.replace("a", "g", 1), "١" * 8 + MBID[8:],
             MBID.replace("-", "")]


@pytest.mark.parametrize("value", BAD_MBIDS)
@pytest.mark.parametrize("route,kind", [("lookup", "artist"), ("lookup", "album"), ("lookup", "track"),
                                        ("credits", "album"), ("credits", "track"), ("extras", "album"),
                                        ("variants", "album"), ("person", None)])
def test_a_musicbrainz_id_that_is_not_a_uuid_is_refused_before_any_upstream_call(replay, route, kind, value):
    params = {"scheme": "musicbrainz", "value": value}
    if kind:
        params["kind"] = kind
    r = client().get(f"/api/v1/{route}", params=params)
    assert r.status_code == 422, r.text
    assert replay.calls == []



# -- enrich ids ----------------------------------------------------------------------

ENRICH_ROUTES = ["/api/v1/enrich", "/enrich"]
BAD_ENRICH_IDS = {
    "musicbrainz_artist": BAD_MBIDS,
    "musicbrainz_release_group": BAD_MBIDS,
    "musicbrainz_recording": ["../..", MBID + "/../..", "%2e%2e%2f", MBID + "\x00", MBID.upper() + "0", MBID + "\n"],
    "musicbrainz_release": ["../..", "a" * 5000],
    "musicbrainz_work": ["../..", "\x00"],
    "musicbrainz_label": ["../..", "١" * 8 + MBID[8:]],
    "isbn_10": ["../..", "123", "١٢٣٤٥٦٧٨٩٠", "012345678\x00", "%2e%2e%2f", "9" * 4000, "0306406152/x"],
    "isbn_13": ["../..", "123", "٩٧٨٠٣٠٦٤٠٦١٥٧", "978030640615\x00", "9" * 4000, "978030640615"],
    "olid": ["../..", "OL1A/../..", "%2e%2e%2f", "OL١A", "OL1A\x00", "OL" + "9" * 4000 + "W", "OL1", "ol1a", "OLA", "OL1Z", "OL1X", "OL1B", "OL45883W\n"],
    "dvdcompare_id": ["../..", "16880/../..", "%2f", "١٦٨٨٠", "16880\x00", "9" * 4000, "1.5", "-1", "16880\n"],
}


@pytest.fixture
def enriched(monkeypatch):
    calls = []

    def fake(external_ids, **kwargs):
        calls.append(external_ids)
        return external_ids

    monkeypatch.setattr("metadatarr.server.routes.run_enrich", fake)
    return calls


@pytest.mark.parametrize("route", ENRICH_ROUTES)
@pytest.mark.parametrize("field,value", [(f, v) for f, vs in BAD_ENRICH_IDS.items() for v in vs])
def test_an_enrich_id_its_scheme_cannot_hold_is_refused_before_any_provider(enriched, route, field, value):
    r = client().post(route, json={"external_ids": {field: value}})
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "invalid id"
    assert r.headers["cache-control"] == "no-store"
    assert enriched == []


@pytest.mark.parametrize("route", ENRICH_ROUTES)
@pytest.mark.parametrize("ids", [
    {"musicbrainz_artist": MBID, "musicbrainz_release_group": MBID, "musicbrainz_recording": MBID},
    {"isbn_10": "0-306-40615-2"}, {"isbn_10": "080442957X"}, {"isbn_13": "978-0-306-40615-7"},
    {"olid": "OL45883W"}, {"olid": "OL26320A"}, {"dvdcompare_id": "16880"},
    {"musicbrainz_artist": "", "isbn_13": "", "olid": "", "dvdcompare_id": ""},
])
def test_enrich_forwards_well_formed_ids(enriched, route, ids):
    r = client().post(route, json={"external_ids": ids})
    assert r.status_code == 200, r.text
    assert len(enriched) == 1


@pytest.mark.parametrize("route", ENRICH_ROUTES)
@pytest.mark.parametrize("field", ["isbn_10", "isbn_13"])
def test_enrich_forwards_an_isbn_with_a_trailing_newline_normalised(enriched, route, field):
    isbn = "080442957X" if field == "isbn_10" else "9780306406157"
    r = client().post(route, json={"external_ids": {field: isbn + "\n"}})
    assert r.status_code == 200, r.text
    assert getattr(enriched[0], field) == isbn


@pytest.mark.parametrize("field,value", [("isbn_10", "080442957X\n"), ("isbn_13", "9780306406157\n"),
                                         ("isbn_13", "978030640615")])
def test_check_external_ids_refuses_an_isbn_the_model_would_not_have_normalised(field, value):
    with pytest.raises(catalog.InvalidId):
        catalog_base.check_external_ids(SimpleNamespace(**{field: value}))


@pytest.mark.parametrize("field,value", [("isbn_13", "978-0-306-40615-7"), ("isbn_10", "0-306-40615-2")])
def test_check_external_ids_accepts_a_hyphenated_isbn(field, value):
    catalog_base.check_external_ids(SimpleNamespace(**{field: value}))


@pytest.mark.parametrize("route", ENRICH_ROUTES)
def test_enrich_accepts_an_uppercase_musicbrainz_uuid_as_the_resolve_route_does(enriched, replay, route):
    upper = MBID.upper()
    r = client().post(route, json={"external_ids": {"musicbrainz_artist": upper}})
    assert r.status_code == 200, r.text
    assert enriched[0].musicbrainz_artist == upper
    resolved = client().post("/api/v1/resolve", json={"ids": {"musicbrainz": upper}, "kind": "artist"})
    assert resolved.status_code != 422, resolved.text
