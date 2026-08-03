"""Row-schema equivalence tests for the tmdb/rawg/tvmaze/jikan/steam batch
migrated onto the engine.

These lock the exact flat-row shape each scraper emits against a realistic
upstream sample, mirroring test_scrapers_migrated.py.
"""
from __future__ import annotations

from metadatarr.scrapers.engine import all_sources
from metadatarr.scrapers.jikan_manga import JikanMangaSource
from metadatarr.scrapers.rawg_games import RAWGGamesSource
from metadatarr.scrapers.steam_games import SteamGamesSource
from metadatarr.scrapers.tmdb_movies import TMDBMoviesSource
from metadatarr.scrapers.tmdb_tv import TMDBTVSource
from metadatarr.scrapers.tvmaze_shows import TVMazeShowsSource


def test_tmdb_movies_map_row_schema():
    src = TMDBMoviesSource()
    m = {
        "id": 603,
        "title": "The Matrix",
        "original_title": "The Matrix",
        "original_language": "en",
        "release_date": "1999-03-31",
        "genre_ids": [28, 878],
        "vote_average": 8.2,
        "vote_count": 24000,
        "popularity": 88.1,
        "adult": False,
        "overview": "x" * 600,
        "poster_path": "/poster.jpg",
    }
    row = src.map_row(m)
    assert row["tmdb_id"] == 603
    assert row["genres"] == ["Action", "Science Fiction"]
    assert len(row["overview"]) == 500
    assert row["entity_type"] == "film"
    assert set(row) == {
        "tmdb_id", "title", "original_title", "original_language",
        "release_date", "genres", "vote_average", "vote_count", "popularity",
        "adult", "overview", "poster_path", "entity_type",
    }


def test_tmdb_movies_map_row_drops_records_without_id():
    assert TMDBMoviesSource().map_row({"id": None, "title": "x"}) is None


def test_tmdb_movies_fetch_advances_page_then_year():
    src = TMDBMoviesSource()
    calls = []

    def fake_get_json(url, params):
        calls.append(dict(params))
        year = params["primary_release_year"]
        page = params["page"]
        if year == 1888 and page == 1:
            return {"total_pages": 2, "results": [{"id": 1, "title": "a"}]}
        if year == 1888 and page == 2:
            return {"total_pages": 2, "results": [{"id": 2, "title": "b"}]}
        return {"total_pages": 1, "results": []}

    src.get_json = fake_get_json
    rows, cursor = src.fetch({"year": 1888, "page": 1})
    assert len(rows) == 1
    assert cursor == {"year": 1888, "page": 2}

    rows, cursor = src.fetch(cursor)
    assert len(rows) == 1
    assert cursor == {"year": 1889, "page": 1}


def test_tmdb_tv_map_row_schema():
    src = TMDBTVSource()
    s = {
        "id": 1399,
        "name": "Game of Thrones",
        "original_name": "Game of Thrones",
        "original_language": "en",
        "first_air_date": "2011-04-17",
        "origin_country": ["US"],
        "genre_ids": [10765],
        "vote_average": 8.4,
        "vote_count": 21000,
        "popularity": 400.1,
        "overview": "y" * 600,
        "poster_path": "/poster2.jpg",
    }
    row = src.map_row(s)
    assert row["tmdb_id"] == 1399
    assert row["genres"] == ["Sci-Fi & Fantasy"]
    assert len(row["overview"]) == 500
    assert row["entity_type"] == "tv_series"
    assert set(row) == {
        "tmdb_id", "name", "original_name", "original_language",
        "first_air_date", "origin_country", "genres", "vote_average",
        "vote_count", "popularity", "overview", "poster_path", "entity_type",
    }


def test_rawg_games_map_row_schema():
    src = RAWGGamesSource()
    g = {
        "id": 3498,
        "slug": "grand-theft-auto-v",
        "name": "Grand Theft Auto V",
        "released": "2013-09-17",
        "metacritic": 92,
        "rating": 4.47,
        "rating_top": 5,
        "ratings_count": 6500,
        "esrb_rating": {"name": "Mature"},
        "genres": [{"name": "Action"}, {"name": "Adventure"}],
        "platforms": [{"platform": {"name": "PC"}}, {"platform": {"name": "PS5"}}],
        "tags": [{"name": "Singleplayer", "language": "eng"},
                 {"name": "Multijoueur", "language": "fra"}],
        "stores": [{"store": {"name": "Steam"}}],
        "developers": [{"name": "Rockstar North"}],
        "publishers": [{"name": "Rockstar Games"}],
        "background_image": "http://example.com/img.jpg",
    }
    row = src.map_row(g)
    assert row["rawg_id"] == 3498
    assert row["esrb_rating"] == "Mature"
    assert row["genres"] == ["Action", "Adventure"]
    assert row["platforms"] == ["PC", "PS5"]
    assert row["tags"] == ["Singleplayer"]  # only "eng" tags kept
    assert row["stores"] == ["Steam"]
    assert row["entity_type"] == "video_game"
    assert set(row) == {
        "rawg_id", "slug", "name", "released", "metacritic", "rating",
        "rating_top", "ratings_count", "esrb_rating", "genres", "platforms",
        "tags", "stores", "developers", "publishers", "background_image",
        "entity_type",
    }


def test_rawg_games_map_row_drops_records_without_id():
    assert RAWGGamesSource().map_row({"id": None}) is None


def test_rawg_games_fetch_stops_without_next():
    src = RAWGGamesSource()
    src.get_json = lambda url, params: {"results": [{"id": 1}], "next": None}
    rows, cursor = src.fetch(1)
    assert len(rows) == 1
    assert cursor is None


def test_tvmaze_shows_map_row_schema():
    src = TVMazeShowsSource()
    s = {
        "id": 1,
        "name": "Under the Dome",
        "type": "Scripted",
        "language": "English",
        "genres": ["Drama", "Science-Fiction"],
        "status": "Ended",
        "runtime": 60,
        "averageRuntime": 60,
        "premiered": "2013-06-24",
        "ended": "2015-09-10",
        "network": {"name": "CBS", "country": {"code": "US"}},
        "rating": {"average": 6.5},
        "schedule": {"time": "22:00", "days": ["Thursday"]},
        "summary": "<p>Small town.</p>",
        "officialSite": "http://example.com",
        "externals": {"imdb": "tt1553656", "thetvdb": 153021, "tvrage": 25988},
        "image": {"medium": "http://example.com/med.jpg"},
    }
    row = src.map_row(s)
    assert row["tvmaze_id"] == 1
    assert row["summary"] == "Small town."
    assert row["network_name"] == "CBS"
    assert row["network_country"] == "US"
    assert set(row) == {
        "tvmaze_id", "name", "type", "language", "genres", "status",
        "runtime", "average_runtime", "premiered", "ended", "network_name",
        "network_country", "rating_average", "schedule_time",
        "schedule_days", "summary", "official_site", "imdb_id",
        "thetvdb_id", "tvrage_id", "image_medium",
    }


def test_tvmaze_shows_fetch_stops_on_404(monkeypatch):
    src = TVMazeShowsSource()

    class FakeResp:
        status_code = 404

    class FakeSession:
        def get(self, *a, **kw):
            return FakeResp()

    src._session = FakeSession()
    src.throttle.wait = lambda: None
    rows, cursor = src.fetch(5)
    assert rows == []
    assert cursor is None


def test_jikan_manga_map_row_schema():
    src = JikanMangaSource()
    m = {
        "mal_id": 1,
        "title": "Monster",
        "title_english": "Monster",
        "title_japanese": "MONSTER",
        "titles": [{"type": "Default", "title": "Monster"}, {"type": "Synonym", "title": "MONSTAA"}],
        "type": "Manga",
        "status": "Finished",
        "chapters": 162,
        "volumes": 18,
        "published": {"prop": {"from": {"year": 1994, "month": 12, "day": 5},
                                "to": {"year": 2001, "month": 12, "day": 20}}},
        "authors": [{"name": "Urasawa, Naoki"}],
        "serializations": [{"name": "Big Comic Original"}],
        "genres": [{"name": "Mystery"}],
        "themes": [{"name": "Psychological"}],
        "demographics": [{"name": "Seinen"}],
        "score": 9.15,
        "scored_by": 60000,
        "rank": 1,
        "popularity": 30,
        "members": 200000,
        "synopsis": "s" * 600,
        "background": "b" * 400,
        "approved": True,
    }
    row = src.map_row(m)
    assert row["mal_id"] == 1
    assert row["aliases"] == ["MONSTAA"]
    assert row["published_from"] == "1994-12-05"
    assert row["published_to"] == "2001-12-20"
    assert len(row["synopsis"]) == 500
    assert len(row["background"]) == 300
    assert set(row) == {
        "mal_id", "title", "title_english", "title_japanese", "aliases",
        "type", "status", "chapters", "volumes", "published_from",
        "published_to", "authors", "serializations", "genres", "themes",
        "demographics", "score", "scored_by", "rank", "popularity",
        "members", "synopsis", "background", "approved",
    }


def test_jikan_manga_map_row_drops_records_without_mal_id():
    assert JikanMangaSource().map_row({"mal_id": None}) is None


def test_jikan_manga_fetch_respects_has_next_page():
    src = JikanMangaSource()
    src.get_json = lambda url, params: {
        "data": [{"mal_id": 1}],
        "pagination": {"has_next_page": False},
    }
    rows, cursor = src.fetch(1)
    assert len(rows) == 1
    assert cursor is None


def test_steam_games_map_row_schema():
    src = SteamGamesSource()
    entry = {
        "appid": 620,
        "name": "Portal 2",
        "developer": "Valve",
        "publisher": "Valve",
        "score_rank": "",
        "positive": 1000,
        "negative": 10,
        "owners": "10,000,000 .. 20,000,000",
        "average_forever": 500,
        "average_2weeks": 0,
        "median_forever": 200,
        "price": "999",
        "discount": "0",
        "ccu": 300,
    }
    row = src.map_row("620", entry)
    assert row["steam_appid"] == 620
    assert row["price_usd"] == 9.99
    assert row["score_rank"] is None  # empty string -> None
    assert row["discount_pct"] == "0"  # non-empty string stays truthy
    assert row["genres"] == []  # enrichment not ported, stays empty
    assert set(row) == {
        "steam_appid", "name", "developer", "publisher", "score_rank",
        "positive_reviews", "negative_reviews", "owners",
        "average_playtime_forever", "average_playtime_2weeks",
        "median_playtime_forever", "price_usd", "discount_pct", "ccu",
        "type", "genres", "categories", "release_date", "is_free",
        "platforms_windows", "platforms_mac", "platforms_linux",
        "metacritic_score", "short_description",
    }


def test_steam_games_map_row_appid_fallback():
    row = SteamGamesSource().map_row("99", {"name": "No appid field"})
    assert row["steam_appid"] == 99


def test_steam_games_fetch_stops_on_empty_page():
    src = SteamGamesSource()
    src.get_json = lambda url, params: {}
    rows, cursor = src.fetch(0)
    assert rows == []
    assert cursor is None


def test_batch1_scrapers_are_registered():
    reg = all_sources()
    assert reg.get("tmdb_movies") is TMDBMoviesSource
    assert reg.get("tmdb_tv") is TMDBTVSource
    assert reg.get("rawg_games") is RAWGGamesSource
    assert reg.get("tvmaze_shows") is TVMazeShowsSource
    assert reg.get("jikan_manga") is JikanMangaSource
    assert reg.get("steam_games") is SteamGamesSource
