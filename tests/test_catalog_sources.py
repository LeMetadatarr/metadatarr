# SPDX-License-Identifier: Apache-2.0
"""Each catalogue source against recorded answers of its catalogue.

The JSON and RSS under ``tests/fixtures/catalog`` are trimmed copies of real
responses, except the ``tmdb_*`` files, which are built by hand in the shape of
TMDB's v3 API. No test reaches the network: an unexpected request is answered
599 by the replay transport and fails the assertion on ``unrouted``."""
from __future__ import annotations

import pytest

from metadatarr import catalog
from metadatarr.catalog import _http
from tests._catalog_fixtures import Replay, ok

RADARR = "https://radarrapi.servarr.com/v1"
SONARR = "https://skyhook.sonarr.tv/v1/tvdb"
LIDARR = "https://api.lidarr.audio/api/v0.4"
TVMAZE = "https://api.tvmaze.com"
MB = "https://musicbrainz.org/ws/2"
OL = "https://openlibrary.org"
TMDB = "https://api.themoviedb.org/3"

RADIOHEAD = "a74b1b7f-71a5-4011-9441-d0b5e4122711"
OK_COMPUTER = "b1392450-e666-3926-a536-22c65f834433"
OKC_RELEASE = "fba5f8fe-c6c8-4511-8562-c9febf482674"
AIRBAG = "4a7fea2e-545b-4c63-bc9a-9943cc3a29d7"
THE_WALL = "f2026101-945b-3d05-9ef4-aa718fc3feef"
WALL_RELEASE = "ded45c32-17c1-4821-b52a-7d056be67442"


def _anilist(*, method, url, params, json_body, timeout):
    query = json_body["query"]
    if "Staff(" in query:
        return ok("anilist_staff_95011.json")
    if json_body["variables"].get("id") == 47 or json_body["variables"].get("idMal") == 47:
        return ok({"data": {"Media": {"id": 47, "idMal": 47, "format": "MOVIE", "title": {"romaji": "AKIRA"},
                                      "startDate": {"year": 1988}}}})
    return ok("anilist_media_1.json")


def recorded() -> Replay:
    r = Replay()
    r.add("GET", f"{RADARR}/movie/603", ok("radarr_movie_603.json"))
    r.add("GET", f"{RADARR}/movie/imdb/tt0133093", ok("radarr_movie_603.json"))
    r.add("GET", f"{RADARR}/movie/collection/2344", ok("radarr_collection_2344.json"))
    r.add("GET", f"{SONARR}/shows/en/81189", ok("skyhook_show_81189.json"))
    r.add("GET", f"{LIDARR}/artist/{RADIOHEAD}", ok("lidarr_artist_radiohead.json"))
    r.add("GET", f"{LIDARR}/album/{OK_COMPUTER}", ok("lidarr_album_okc.json"))
    r.add("GET", f"{RADARR}/movie/862", ok("radarr_movie_862.json"))
    r.add("GET", f"{LIDARR}/album/{THE_WALL}", ok("lidarr_album_wall.json"))
    r.add("GET", f"{MB}/release-group/{THE_WALL}", ok("mb_rg_wall.json"), {"inc": "releases+artist-credits", "fmt": "json"})
    r.add("GET", f"{MB}/release/{WALL_RELEASE}", ok("mb_release_wall.json"), {"inc": "recordings", "fmt": "json"})
    r.add("GET", f"{OL}/books/OL61027603M.json", ok("ol_isbn_9780747532743.json"))
    r.add("GET", f"{TVMAZE}/shows/169", ok("tvmaze_show_169.json"), {"embed[]": ["seasons"]})
    r.add("GET", f"{TVMAZE}/shows/169", ok("tvmaze_show_169.json"), {"embed[]": ["cast", "crew"]})
    r.add("GET", f"{TVMAZE}/lookup/shows", ok("tvmaze_lookup_tvdb.json"), {"thetvdb": "81189"})
    r.add("GET", f"{TVMAZE}/seasons/753", ok("tvmaze_season_753.json"))
    r.add("GET", f"{TVMAZE}/seasons/753/episodes", ok("tvmaze_season_753_episodes.json"))
    r.add("GET", f"{TVMAZE}/people/14245", ok("tvmaze_person_14245.json"))
    r.add("GET", f"{TVMAZE}/people/14245/castcredits", ok("tvmaze_person_castcredits.json"),
          {"embed[]": ["show", "character"]})
    r.add("GET", f"{TVMAZE}/people/14245/crewcredits", ok("tvmaze_person_crewcredits.json"), {"embed": "show"})
    r.add("GET", f"{MB}/artist/{RADIOHEAD}", ok("mb_artist.json"), {"inc": "aliases", "fmt": "json"})
    r.add("GET", f"{MB}/artist/{RADIOHEAD}", ok("mb_artist.json"), {"inc": "aliases+url-rels", "fmt": "json"})
    r.add("GET", f"{MB}/release-group", ok("mb_rg_browse.json"), {"artist": RADIOHEAD, "limit": 100, "fmt": "json"})
    r.add("GET", f"{MB}/release-group/{OK_COMPUTER}", ok("mb_rg.json"), {"inc": "releases+artist-credits", "fmt": "json"})
    for inc in ("recordings", "artist-credits+labels+artist-rels"):
        r.add("GET", f"{MB}/release/{OKC_RELEASE}", ok("mb_release.json"), {"inc": inc, "fmt": "json"})
    r.add("GET", f"{MB}/recording/{AIRBAG}", ok("mb_recording.json"), {"inc": "artist-credits", "fmt": "json"})
    r.add("GET", f"{MB}/recording/{AIRBAG}", ok("mb_recording.json"),
          {"inc": "artist-credits+artist-rels+work-rels+work-level-rels", "fmt": "json"})
    r.add("POST", "https://graphql.anilist.co", _anilist)
    r.add("GET", f"{OL}/authors/OL23919A.json", ok("ol_author_OL23919A.json"))
    r.add("GET", f"{OL}/authors/OL23919A/works.json", ok("ol_author_OL23919A_works.json"), {"limit": 200})
    r.add("GET", f"{OL}/works/OL82563W.json", ok("ol_work_OL82563W.json"))
    r.add("GET", f"{OL}/isbn/9780747532743.json", ok("ol_isbn_9780747532743.json"))
    r.add("GET", "https://itunes.apple.com/lookup", ok("itunes_lookup_1584274529.json"),
          {"id": "1584274529", "entity": "podcast"})
    r.add("GET", "https://itunes.apple.com/lookup", ok("itunes_lookup_536258179.json"),
          {"id": "536258179", "entity": "podcast"})
    r.add("GET", "https://feeds.podcastindex.org/pc20.xml", ok("feed_pc20.xml"))
    r.add("GET", "https://feeds.megaphone.fm/SBP4591212513", ok("feed_nightvale.xml"))
    r.add("GET", "https://librivox.org/api/feed/audiobooks/", ok("librivox_47.json"),
          {"id": "47", "format": "json", "extended": "1"})
    r.add("GET", f"{TMDB}/movie/603", ok("tmdb_movie_603.json"), {"append_to_response": "external_ids"})
    r.add("GET", f"{TMDB}/movie/603", ok("tmdb_movie_603.json"), {"append_to_response": "credits"})
    r.add("GET", f"{TMDB}/find/tt0133093", ok("tmdb_find_tt0133093.json"), {"external_source": "imdb_id"})
    r.add("GET", f"{TMDB}/find/nm0000206", ok("tmdb_find_nm0000206.json"), {"external_source": "imdb_id"})
    r.add("GET", f"{TMDB}/tv/1396", ok("tmdb_tv_1396.json"), {"append_to_response": "external_ids"})
    r.add("GET", f"{TMDB}/tv/1396", ok("tmdb_tv_1396.json"), {"append_to_response": "aggregate_credits"})
    r.add("GET", f"{TMDB}/tv/1396/season/1", ok("tmdb_tv_1396_season_1.json"))
    r.add("GET", f"{TMDB}/collection/2344", ok("tmdb_collection_2344.json"))
    r.add("GET", f"{TMDB}/person/6384", ok("tmdb_person_6384.json"),
          {"append_to_response": "combined_credits,external_ids"})
    return r


@pytest.fixture
def replay(monkeypatch):
    r = recorded()
    monkeypatch.setattr(_http, "send", r)
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    catalog.reset_cache()
    yield r
    catalog.reset_cache()


def ask(method, scheme, value, kind=None, provider=None):
    answer = catalog.ask(method, scheme, value, kind, provider=provider)
    assert answer.errors == [], answer.errors
    return answer


def roles(credits):
    return [(c.role, c.person.name, c.character) for c in credits]


# -- skyhook --------------------------------------------------------------------

def test_skyhook_movie_by_tmdb_and_by_imdb(replay):
    for scheme, value in (("tmdb", "603"), ("imdb", "tt0133093")):
        a = ask("lookup", scheme, value, "movie")
        item = a.value
        assert a.providers == ["skyhook"]
        assert (item.kind, item.title, item.year, item.release_date, item.runtime_min) == (
            "movie", "The Matrix", 1999, "1999-03-31", 136)
        assert item.ext_ids == {"tmdb": "603", "imdb": "tt0133093"}
        assert item.poster_url.startswith("https://image.tmdb.org/")
        assert item.extra["collection"] == {"tmdb": "2344", "name": "The Matrix Collection"}
    assert replay.unrouted == []


def test_skyhook_collection_children_are_movies_in_release_order(replay):
    item = ask("lookup", "tmdb", "2344", "collection").value
    assert item.title == "The Matrix Collection"
    years = [c.year for c in item.children]
    assert years == sorted(years) and len(years) == 4
    assert [c.position for c in item.children] == [1, 2, 3, 4]
    assert all(c.kind == "movie" and c.ext_ids.get("tmdb") for c in item.children)
    assert item.children[0].title == "The Matrix"


def test_skyhook_movie_credits_cast_in_billing_order_crew_normalised(replay):
    credits = ask("credits", "tmdb", "603", "movie").value
    cast = [c for c in credits if c.role == "actor"]
    assert [(c.person.name, c.character, c.position) for c in cast[:3]] == [
        ("Keanu Reeves", "Neo", 0), ("Laurence Fishburne", "Morpheus", 1), ("Carrie-Anne Moss", "Trinity", 2)]
    assert cast[0].person.ext_ids == {"tmdb": "6384"}
    directors = [c.person.name for c in credits if c.role == "director"]
    assert directors == ["Lana Wachowski", "Lilly Wachowski"]
    assert {"writer", "producer", "executive-producer"} <= {c.role for c in credits}
    studio = [c for c in credits if c.role == "studio"]
    assert studio and studio[0].person.kind == "company" and studio[0].person.name == "Village Roadshow Pictures"


def test_skyhook_series_children_are_seasons_named_by_series_and_number(replay):
    item = ask("lookup", "tvdb", "81189", "series").value
    assert (item.title, item.year) == ("Breaking Bad", 2008)
    assert item.ext_ids == {"tvdb": "81189", "tmdb": "1396", "imdb": "tt0903747", "tvmaze": "169"}
    assert [(c.kind, c.title, c.position, c.ext_ids["tvdb"]) for c in item.children] == [
        ("season", "Specials", 0, "81189/0"), ("season", "Season 1", 1, "81189/1"), ("season", "Season 2", 2, "81189/2")]
    assert all(c.children == [] for c in item.children)


def test_skyhook_season_children_are_its_episodes_only(replay):
    item = ask("lookup", "tvdb", "81189/1", "season").value
    assert (item.kind, item.position, item.release_date) == ("season", 1, "2008-01-20")
    assert [e.position for e in item.children] == [1, 2, 3, 4, 5, 6, 7]
    assert item.children[0].title == "Pilot" and item.children[0].extra["season"] == 1
    assert all(e.kind == "episode" and e.ext_ids.get("tvdb") for e in item.children)


def test_skyhook_unknown_season_is_not_found(replay):
    assert catalog.ask("lookup", "tvdb", "81189/9", "season").value is None


def test_skyhook_malformed_season_value_is_refused_before_any_request(replay):
    with pytest.raises(catalog.InvalidId):
        catalog.ask("lookup", "tvdb", "81189", "season")
    assert replay.calls == []


def test_skyhook_series_credits_carry_characters_and_network(replay):
    credits = ask("credits", "tvdb", "81189", "series").value
    assert roles(credits)[:2] == [("actor", "Bryan Cranston", "Walter White"), ("actor", "Anna Gunn", "Skyler White")]
    network = [c for c in credits if c.role == "network"]
    assert network[0].person.name == "AMC" and network[0].person.kind == "company"


def test_skyhook_artist_children_are_albums_sorted_by_date(replay):
    item = ask("lookup", "musicbrainz", RADIOHEAD, "artist").value
    assert (item.kind, item.title) == ("artist", "Radiohead")
    dated = [c.release_date for c in item.children if c.release_date]
    assert dated == sorted(dated)
    assert {c.kind for c in item.children} == {"album"}
    kid_a = next(c for c in item.children if c.title == "Kid A")
    assert kid_a.ext_ids == {"musicbrainz": "e75c0549-ad55-39e3-8025-c72c5d4a3c5d"}


def test_skyhook_album_tracks_come_from_the_common_official_release(replay):
    item = ask("lookup", "musicbrainz", OK_COMPUTER, "album").value
    assert (item.title, item.year) == ("OK Computer", 1997)
    assert item.extra["release"]["musicbrainz"] == "9c1e5e9e-9f40-4cd8-94a4-785fa5d0b613"
    assert len(item.children) == 12
    assert item.children[0].title == "Airbag" and item.children[0].position == 1
    assert item.children[0].ext_ids == {"musicbrainz": AIRBAG}
    assert 4.7 < item.children[0].runtime_min < 4.8


# -- TVmaze ---------------------------------------------------------------------

def test_tvmaze_series_by_tvdb_goes_through_its_lookup(replay):
    item = ask("lookup", "tvdb", "81189", "series", provider="tvmaze").value
    assert item.ext_ids == {"tvmaze": "169", "tvdb": "81189", "imdb": "tt0903747"}
    assert [c.position for c in item.children] == [1, 2, 3, 4, 5]
    assert item.children[0].ext_ids == {"tvmaze": "753"}
    assert "<" not in item.overview


def test_tvmaze_season_episodes(replay):
    item = ask("lookup", "tvmaze", "753", "season").value
    assert item.position == 1 and len(item.children) == 7
    assert item.children[0].title == "Pilot" and item.children[0].extra["season"] == 1


def test_tvmaze_credits_cast_crew_network(replay):
    credits = ask("credits", "tvmaze", "169", "series").value
    assert roles(credits)[0] == ("actor", "Bryan Cranston", "Walter White")
    assert credits[0].person.ext_ids == {"tvmaze": "14245"}
    by_role = {c.role for c in credits}
    assert {"consulting-producer", "cinematographer", "producer", "network"} <= by_role


def test_tvmaze_person_filmography_has_items_and_characters(replay):
    details = ask("person", "tvmaze", "14245").value
    assert (details.person.name, details.person.birth_date, details.person.country) == (
        "Bryan Cranston", "1956-03-07", "US")
    first = details.credits[0]
    assert (first.role, first.character, first.item.title, first.item.kind) == (
        "actor", "Walter White", "Breaking Bad", "series")
    assert ("executive-producer", "SuperMansion") in [(c.role, c.item.title) for c in details.credits]
    assert ("creator", "Sneaky Pete") in [(c.role, c.item.title) for c in details.credits]


# -- MusicBrainz ------------------------------------------------------------------

def test_musicbrainz_album_by_release_group_with_tracks_of_its_official_release(replay):
    item = ask("lookup", "musicbrainz", OK_COMPUTER, "album", provider="musicbrainz").value
    assert item.title == "OK Computer" and item.release_date == "1997-05-21"
    assert item.extra["release"] == {"musicbrainz": OKC_RELEASE}
    assert item.extra["artist"] == {"name": "Radiohead", "musicbrainz": RADIOHEAD}
    assert [t.position for t in item.children] == list(range(1, 13))
    assert item.children[0].ext_ids == {"musicbrainz": AIRBAG}


def test_musicbrainz_album_credits_use_music_roles(replay):
    credits = ask("credits", "musicbrainz", OK_COMPUTER, "album").value
    got = {(c.role, c.person.name) for c in credits}
    assert ("artist", "Radiohead") in got
    assert ("producer-music", "Nigel Godrich") in got  # MusicBrainz "producer" is a record producer
    assert ("mastering", "Chris Blair") in got and ("conductor", "Nick Ingman") in got
    assert ("cover-artist", "Stanley Donwood") in got  # "design/illustration"
    label = [c for c in credits if c.role == "label"]
    assert label[0].person.kind == "company" and label[0].note == "TCNODATA 02"
    assert next(c for c in credits if c.role == "artist").person.kind == "group"


def test_musicbrainz_track_credits_merge_instruments_and_reach_the_work(replay):
    credits = ask("credits", "musicbrainz", AIRBAG, "track").value
    jonny = [c for c in credits if c.person.name == "Jonny Greenwood" and c.role == "performer"]
    assert len(jonny) == 1, "one performer credit per person, instruments joined in the note"
    assert {"guitar", "organ"} <= set(jonny[0].note.split(", "))
    writers = {c.person.name for c in credits if c.role == "writer"}
    assert {"Thom Yorke", "Colin Greenwood"} <= writers  # from the work's relations


def test_musicbrainz_person_is_a_group_with_release_groups(replay):
    details = ask("person", "musicbrainz", RADIOHEAD).value
    p = details.person
    assert (p.name, p.kind, p.birth_date) == ("Radiohead", "group", None)
    assert p.extra["formed"] == "1991"
    assert p.ext_ids["musicbrainz"] == RADIOHEAD
    assert details.credits and all(c.role == "artist" and c.item.kind == "album" for c in details.credits)


def test_musicbrainz_refuses_a_value_that_is_not_an_mbid_without_a_request(replay):
    with pytest.raises(catalog.InvalidId):
        catalog.ask("lookup", "musicbrainz", "not-an-id", "track")
    assert replay.calls == []


# -- AniList ----------------------------------------------------------------------

def test_anilist_lookup_by_anilist_and_by_mal(replay):
    for scheme in ("anilist", "mal"):
        item = ask("lookup", scheme, "1", "series").value
        assert (item.title, item.original_title, item.year, item.release_date) == (
            "Cowboy Bebop", "カウボーイビバップ", 1998, "1998-04-03")
        assert item.ext_ids == {"anilist": "1", "mal": "1"} and item.children == []
    assert [b["variables"] for b in replay.bodies] == [{"id": 1}, {"idMal": 1}]


def test_anilist_credits_voice_actors_staff_studios(replay):
    credits = ask("credits", "anilist", "1", "series").value
    va = [c for c in credits if c.role == "voice-actor"]
    assert (va[0].person.name, va[0].character, va[0].note) == ("Kouichi Yamadera", "Spike Spiegel", "Japanese")
    assert va[0].person.ext_ids == {"anilist": "95011"}
    got = {(c.role, c.person.name) for c in credits}
    assert ("adapted-from", "Hajime Yatate") in got  # "Original Creator"
    assert ("writer", "Keiko Nobumoto") in got  # "Series Composition"
    assert ("director", "Shinichirou Watanabe") in got
    studios = {(c.role, c.person.name, c.note) for c in credits if c.person.kind == "company"}
    assert ("studio", "Sunrise", "main") in studios and ("producer", "Bandai Visual", "") in studios


def test_anilist_person_roles_and_bracketed_notes(replay):
    details = ask("person", "anilist", "95011").value
    assert (details.person.name, details.person.birth_date) == ("Kouichi Yamadera", "1961-06-17")
    assert "山寺宏一" in details.person.aliases
    first = details.credits[0]
    assert (first.role, first.character, first.item.title) == (
        "voice-actor", "Momo Yozakura", "Mission: Yozakura Family Season 2 Part 2")
    insert = [c for c in details.credits if c.note.startswith("eps")]
    assert insert and insert[0].role == "insert-song-performance"


# -- Open Library -----------------------------------------------------------------

def test_openlibrary_author_with_works_and_remote_ids(replay):
    item = ask("lookup", "openlibrary", "OL23919A").value
    assert (item.kind, item.title) == ("author", "J. K. Rowling")
    assert item.ext_ids["wikidata"] == "Q34660" and item.ext_ids["openlibrary"] == "OL23919A"
    assert len(item.children) == 4 and all(c.kind == "book" for c in item.children)
    assert item.children[0].ext_ids["openlibrary"].endswith("W")


def test_openlibrary_book_by_isbn_answers_with_the_work(replay):
    item = ask("lookup", "isbn", "978-0-7475-3274-3", "book").value
    assert item.title == "Harry Potter and the Philosopher's Stone"
    assert item.ext_ids == {"openlibrary": "OL82563W", "openlibrary_edition": "OL61027603M", "isbn": "9780747532743"}
    assert item.extra["edition"]["openlibrary"] == "OL61027603M"


def test_openlibrary_book_credits_author_and_publisher(replay):
    credits = ask("credits", "isbn", "9780747532743", "book").value
    assert [(c.role, c.person.name) for c in credits] == [("author", "J. K. Rowling"), ("publisher", "Bloomsbury")]
    assert credits[0].person.birth_date == "1965-07-31"


def test_openlibrary_person_filmography(replay):
    details = ask("person", "openlibrary", "OL23919A").value
    assert details.person.birth_date == "1965-07-31" and details.person.bio
    assert len(details.credits) == 4 and details.credits[0].role == "author"


# -- Apple Podcasts ---------------------------------------------------------------

def test_apple_show_episodes_from_the_feed_oldest_first(replay):
    item = ask("lookup", "apple_podcasts", "1584274529", "show").value
    assert (item.kind, item.title) == ("show", "Podcasting 2.0")
    assert item.extra["feed_url"] == "https://feeds.podcastindex.org/pc20.xml"
    dates = [e.release_date for e in item.children]
    assert len(dates) == 3 and dates == sorted(dates)
    assert item.release_date == dates[0]


def test_apple_credits_from_podcast_person_tags(replay):
    credits = ask("credits", "apple_podcasts", "1584274529", "show").value
    assert [(c.role, c.person.name, c.note) for c in credits] == [
        ("host", "Adam Curry", ""), ("host", "Dave Jones", ""), ("guest", "Sam Sethi", "1 episode")]
    assert credits[0].person.image_url.endswith("adam_avatar.jpg")


def test_apple_feed_without_person_tags_names_its_author(replay):
    credits = ask("credits", "apple_podcasts", "536258179", "show").value
    assert [(c.role, c.person.name, c.note) for c in credits] == [("creator", "Night Vale Presents", "feed author")]


def test_feed_cut_short_keeps_the_channel_and_whole_items():
    from metadatarr.catalog.sources.apple_podcasts import parse_feed
    from tests._catalog_fixtures import fixture

    body = fixture("feed_pc20.xml")
    cut = body[: body.index(b"</item>") + 200]
    feed = parse_feed(cut)
    assert feed.title == "Podcasting 2.0"
    assert [p[0] for p in feed.people] == ["Adam Curry", "Dave Jones"]
    assert len(feed.episodes) == 1


# -- LibriVox ---------------------------------------------------------------------

def test_librivox_audiobook_chapters(replay):
    item = ask("lookup", "librivox", "47").value
    assert (item.kind, item.title) == ("audiobook", "Count of Monte Cristo")
    assert [c.position for c in item.children] == [1, 2, 3, 4, 5]
    assert item.children[0].extra["readers"] == ["Kristin LeMoine"]


def test_librivox_narrators_with_their_chapters(replay):
    credits = ask("credits", "librivox", "47").value
    assert [(c.role, c.person.name, c.note) for c in credits] == [
        ("author", "Alexandre Dumas", ""), ("narrator", "Kristin LeMoine", "chapters 1"),
        ("narrator", "Gord Mackenzie", "chapters 2-4"), ("narrator", "Betsie Bush", "chapters 5")]
    assert credits[0].person.ext_ids == {"librivox_author": "431"}
    assert credits[1].person.ext_ids == {"librivox_reader": "14"}


# -- TMDB (hand-built fixtures) -----------------------------------------------------

def test_tmdb_needs_its_key(replay, monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY")
    with pytest.raises(catalog.NotSupported):
        catalog.ask("person", "tmdb", "6384")


def test_tmdb_movie_and_credits(replay):
    item = ask("lookup", "tmdb", "603", "movie", provider="tmdb").value
    assert (item.title, item.year, item.ext_ids) == ("The Matrix", 1999,
                                                     {"tmdb": "603", "imdb": "tt0133093", "wikidata": "Q83495"})
    credits = ask("credits", "imdb", "tt0133093", "movie", provider="tmdb").value
    assert roles(credits)[:2] == [("actor", "Keanu Reeves", "Neo"), ("actor", "Laurence Fishburne", "Morpheus")]
    got = {(c.role, c.person.name) for c in credits}
    assert {("director", "Lana Wachowski"), ("screenwriter", "Lana Wachowski"), ("composer", "Don Davis"),
            ("cinematographer", "Bill Pope"), ("studio", "Village Roadshow Pictures")} <= got
    assert all("test-key" not in call for call in replay.calls)


def test_tmdb_series_seasons_and_episodes(replay):
    series = ask("lookup", "tmdb", "1396", "series").value
    assert series.ext_ids["tvdb"] == "81189"
    assert [s.ext_ids["tmdb"] for s in series.children] == ["1396/0", "1396/1"]
    season = ask("lookup", "tmdb", "1396/1", "season").value
    assert [(e.position, e.title) for e in season.children] == [(1, "Pilot"), (2, "Cat's in the Bag...")]
    credits = ask("credits", "tmdb", "1396", "series").value
    got = {(c.role, c.person.name, c.character) for c in credits}
    assert {("creator", "Vince Gilligan", ""), ("actor", "Bryan Cranston", "Walter White"),
            ("executive-producer", "Vince Gilligan", ""), ("writer", "Vince Gilligan", ""),
            ("network", "AMC", "")} <= got


def test_tmdb_person_by_imdb_with_movie_and_tv_credits(replay):
    details = ask("person", "imdb", "nm0000206").value
    assert details.person.ext_ids == {"tmdb": "6384", "imdb": "nm0000206", "wikidata": "Q43416"}
    assert [(c.role, c.item.kind, c.item.title, c.character) for c in details.credits] == [
        ("actor", "movie", "The Matrix", "Neo"), ("actor", "series", "Swedish Dicks", "Tex"),
        ("director", "movie", "Man of Tai Chi", "")]


def test_every_source_stays_offline(replay):
    for method, scheme, value, kind in [("lookup", "tmdb", "603", "movie"), ("credits", "tvdb", "81189", "series"),
                                        ("person", "tvmaze", "14245", None)]:
        catalog.ask(method, scheme, value, kind)
    assert replay.unrouted == []


# -- kinds, editions, discs, roles ---------------------------------------------------

def test_anilist_kind_follows_the_format_when_the_caller_gave_none(replay):
    assert ask("lookup", "anilist", "47").value.kind == "movie"
    assert ask("lookup", "mal", "47").value.kind == "movie"
    assert ask("lookup", "anilist", "1").value.kind == "series"  # format TV
    assert ask("lookup", "anilist", "47", "series").value.kind == "series"  # an explicit kind is kept


def test_openlibrary_edition_lookup_keeps_the_edition_id(replay):
    item = ask("lookup", "openlibrary", "OL61027603M").value
    assert item.ext_ids == {"openlibrary": "OL82563W", "openlibrary_edition": "OL61027603M"}
    by_isbn = ask("lookup", "isbn", "9780747532743").value
    assert by_isbn.ext_ids["openlibrary_edition"] == "OL61027603M"


@pytest.mark.parametrize("provider,release", [("skyhook", "14db3839-4007-3b46-9e7c-619f37ac19a4"),
                                              ("musicbrainz", WALL_RELEASE)])
def test_two_disc_album_tracks_count_on_across_discs(replay, provider, release):
    item = ask("lookup", "musicbrainz", THE_WALL, "album", provider=provider).value
    assert item.extra["release"]["musicbrainz"] == release
    assert [t.position for t in item.children] == list(range(1, 27))
    second = item.children[13]
    assert (second.extra["medium"], second.extra["disc_position"]) == (2, 1)
    assert item.children[12].extra["medium"] == 1 and item.children[12].extra["disc_position"] == 13


def test_casting_is_never_a_voice_actor(replay):
    credits = ask("credits", "tmdb", "862", "movie").value
    mickie = [c.role for c in credits if c.person.name == "Mickie McGowan"]
    assert mickie == ["casting"]
