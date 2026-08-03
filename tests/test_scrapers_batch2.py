"""Row-schema equivalence tests for the musicbrainz/anilist/metal/gutenberg/
podcastindex/radiobrowser/audiodb batch migrated onto the engine.

These lock the exact flat-row shape each scraper emits against a realistic
upstream sample, mirroring test_scrapers_migrated.py / test_scrapers_batch1.py.
"""
from __future__ import annotations

from metadatarr.scrapers.engine import all_sources
from metadatarr.scrapers.musicbrainz_artists import MusicBrainzArtistsSource
from metadatarr.scrapers.musicbrainz_releases import MusicBrainzReleasesSource
from metadatarr.scrapers.anilist_anime import AniListAnimeSource
from metadatarr.scrapers.metal_archives import MetalArchivesSource
from metadatarr.scrapers.gutenberg_books import GutenbergBooksSource
from metadatarr.scrapers.podcastindex_podcasts import (
    PodcastIndexPodcastsSource,
    map_chart_row,
    map_search_row,
    map_browse_row,
)
from metadatarr.scrapers.radiobrowser_stations import RadioBrowserStationsSource
from metadatarr.scrapers.audiodb_artists import AudioDBArtistsSource


def test_musicbrainz_artists_map_row_schema():
    src = MusicBrainzArtistsSource()
    a = {
        "id": "mb-1",
        "name": "Radiohead",
        "sort-name": "Radiohead",
        "type": "Group",
        "gender": None,
        "country": "GB",
        "area": {"name": "United Kingdom"},
        "life-span": {"begin": "1985", "end": None, "ended": False},
        "disambiguation": "",
        "aliases": [{"name": "RDH"}],
        "tags": [{"name": "rock"}],
        "ipis": ["001"],
        "isnis": ["002"],
    }
    row = src.map_row(a)
    assert row["mb_id"] == "mb-1"
    assert row["area"] == "United Kingdom"
    assert row["begin_date"] == "1985"
    assert row["aliases"] == ["RDH"]
    assert set(row) == {
        "mb_id", "name", "sort_name", "type", "gender", "country", "area",
        "begin_date", "end_date", "ended", "disambiguation", "aliases",
        "tags", "ipi_codes", "isni_codes",
    }


def test_musicbrainz_artists_fetch_stops_at_count():
    src = MusicBrainzArtistsSource()
    src.get_json = lambda url, params: {"artists": [{"id": "a1"}], "count": 1}
    rows, cursor = src.fetch(0)
    assert len(rows) == 1
    assert cursor is None


def test_musicbrainz_releases_map_row_schema():
    src = MusicBrainzReleasesSource()
    rg = {
        "id": "rg-1",
        "title": "OK Computer",
        "primary-type": "Album",
        "secondary-types": [],
        "first-release-date": "1997-05-21",
        "artist-credit": [{"artist": {"name": "Radiohead", "id": "mb-1"}}],
        "tags": [{"name": "alt rock"}],
        "disambiguation": "",
    }
    row = src.map_row(rg)
    assert row["mb_release_group_id"] == "rg-1"
    assert row["artist_names"] == ["Radiohead"]
    assert row["artist_mb_ids"] == ["mb-1"]
    assert set(row) == {
        "mb_release_group_id", "title", "type", "secondary_types",
        "first_release_date", "artist_names", "artist_mb_ids", "tags",
        "disambiguation",
    }


def test_musicbrainz_releases_fetch_stops_at_count():
    src = MusicBrainzReleasesSource()
    src.get_json = lambda url, params: {"release-groups": [{"id": "rg1"}], "count": 1}
    rows, cursor = src.fetch(0)
    assert len(rows) == 1
    assert cursor is None


def test_anilist_map_row_schema():
    src = AniListAnimeSource()
    m = {
        "id": 1,
        "idMal": 21,
        "title": {"romaji": "Cowboy Bebop", "english": "Cowboy Bebop", "native": "カウボーイビバップ"},
        "type": "ANIME",
        "format": "TV",
        "status": "FINISHED",
        "episodes": 26,
        "duration": 24,
        "chapters": None,
        "volumes": None,
        "countryOfOrigin": "JP",
        "source": "ORIGINAL",
        "startDate": {"year": 1998, "month": 4, "day": 3},
        "endDate": {"year": 1999, "month": 4, "day": 24},
        "season": "SPRING",
        "seasonYear": 1998,
        "genres": ["Action"],
        "tags": [{"name": "Space", "category": "Setting", "isAdult": False}],
        "studios": {"nodes": [{"id": 14, "name": "Sunrise"}]},
        "averageScore": 86,
        "popularity": 100000,
        "favourites": 5000,
        "isAdult": False,
    }
    row = src.map_row(m)
    assert row["anilist_id"] == 1
    assert row["start_date"] == "1998-04-03"
    assert row["tags"] == ["Space"]
    assert row["studios"] == ["Sunrise"]
    assert set(row) == {
        "anilist_id", "mal_id", "title_romaji", "title_english", "title_native",
        "type", "format", "status", "episodes", "duration", "chapters", "volumes",
        "country_of_origin", "source_material", "start_date", "end_date", "season",
        "season_year", "genres", "tags", "studios", "studio_ids", "average_score",
        "popularity", "favourites", "is_adult",
    }


def test_anilist_fetch_advances_page_then_type(monkeypatch):
    src = AniListAnimeSource()
    src.media_types = ["ANIME", "MANGA"]

    class FakeResp:
        def __init__(self, payload, status=200):
            self._payload = payload
            self.status_code = status
            self.headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    class FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            page = json["variables"]["page"]
            mtype = json["variables"]["type"]
            if mtype == "ANIME" and page == 1:
                return FakeResp({"data": {"Page": {"pageInfo": {"hasNextPage": True}, "media": [{"id": 1}]}}})
            if mtype == "ANIME" and page == 2:
                return FakeResp({"data": {"Page": {"pageInfo": {"hasNextPage": False}, "media": [{"id": 2}]}}})
            return FakeResp({"data": {"Page": {"pageInfo": {"hasNextPage": False}, "media": []}}})

    src._session = FakeSession()
    src.throttle.wait = lambda: None

    rows, cursor = src.fetch({"type_idx": 0, "page": 1})
    assert len(rows) == 1
    assert cursor == {"type_idx": 0, "page": 2}

    rows, cursor = src.fetch(cursor)
    assert len(rows) == 1
    assert cursor == {"type_idx": 1, "page": 1}


def test_metal_archives_map_row_schema():
    src = MetalArchivesSource()
    row_data = ['<a href="https://www.metal-archives.com/bands/Metallica/125">Metallica</a>',
                "United States", "Thrash Metal", "Active"]
    row = src.map_row(row_data)
    assert row["ma_id"] == "125"
    assert row["name"] == "Metallica"
    assert row["country"] == "United States"
    assert set(row) == {"ma_id", "name", "url", "country", "genre", "status"}


def test_metal_archives_fetch_stops_at_total():
    src = MetalArchivesSource()
    src.get_json = lambda url, params: {
        "iTotalRecords": 1,
        "aaData": [['<a href="/bands/X/1">X</a>', "US", "Rock", "Active"]],
    }
    rows, cursor = src.fetch(0)
    assert len(rows) == 1
    assert cursor is None


def test_gutenberg_map_row_schema():
    src = GutenbergBooksSource()
    b = {
        "id": 84,
        "title": "Frankenstein",
        "authors": [{"name": "Shelley, Mary", "birth_year": 1797, "death_year": 1851}],
        "translators": [],
        "subjects": [f"s{i}" for i in range(40)],
        "bookshelves": [f"b{i}" for i in range(20)],
        "languages": ["en"],
        "copyright": False,
        "media_type": "Text",
        "download_count": 5000,
        "formats": {"text/plain": "url1", "application/epub+zip": "url2"},
    }
    row = src.map_row(b)
    assert row["gutenberg_id"] == 84
    assert row["has_text"] is True
    assert row["has_epub"] is True
    assert len(row["subjects"]) == 30
    assert len(row["bookshelves"]) == 15
    assert row["entity_type"] == "book"
    assert set(row) == {
        "gutenberg_id", "title", "authors", "translators", "subjects",
        "bookshelves", "languages", "copyright", "media_type",
        "download_count", "has_text", "has_epub", "entity_type",
    }


def test_gutenberg_fetch_follows_next_url():
    src = GutenbergBooksSource()
    src.get_json = lambda url, params: {"results": [{"id": 1}], "next": "https://gutendex.com/books/?page=2"}
    rows, cursor = src.fetch("https://gutendex.com/books/")
    assert len(rows) == 1
    assert cursor == "https://gutendex.com/books/?page=2"


def test_gutenberg_fetch_stops_when_empty():
    src = GutenbergBooksSource()
    src.get_json = lambda url, params: {"results": [], "next": None}
    rows, cursor = src.fetch("https://gutendex.com/books/")
    assert rows == []
    assert cursor is None


def test_podcastindex_map_chart_row():
    entry = {
        "id": {"attributes": {"im:id": "123"}},
        "im:name": {"label": "The Daily"},
        "im:artist": {"label": "NYT"},
        "im:image": [{"label": "img1"}, {"label": "img2"}],
        "link": {"attributes": {"href": "https://example.com/podcast"}},
    }
    row = map_chart_row(entry, "us", "News")
    assert row["itunes_id"] == "123"
    assert row["title"] == "The Daily"
    assert row["image"] == "img2"
    assert row["country_charts"] == ["us"]
    assert row["source"] == "itunes_rss"
    assert set(row) == {
        "itunes_id", "title", "author", "image", "genres", "url",
        "description", "language", "episode_count", "explicit", "feed_url",
        "country_charts", "source", "entity_type",
    }


def test_podcastindex_map_search_row():
    e = {
        "collectionId": 456,
        "collectionName": "Serial",
        "artistName": "This American Life",
        "artworkUrl600": "img600",
        "genres": ["True Crime"],
        "collectionViewUrl": "https://example.com/serial",
        "trackCount": 12,
        "contentAdvisoryRating": "Explicit",
        "feedUrl": "https://example.com/feed.xml",
    }
    row = map_search_row(e)
    assert row["itunes_id"] == "456"
    assert row["explicit"] is True
    assert row["source"] == "itunes_search"


def test_podcastindex_map_row_drops_without_id():
    assert map_chart_row({"id": {}}, "us", "News") is None
    assert map_search_row({}) is None
    assert map_browse_row({"id": {}}, "us", "News") is None


def test_podcastindex_fetch_charts_step_advances_genre_then_country():
    src = PodcastIndexPodcastsSource()
    src.get_json = None
    src._get = lambda url: {"feed": {"entry": []}}
    rows, cursor = src.fetch({"stage": "charts", "cidx": 0, "gidx": 0})
    assert cursor["stage"] == "charts"
    assert cursor["cidx"] == 0
    assert cursor["gidx"] == 1


def test_podcastindex_registered():
    assert all_sources().get("podcastindex_podcasts") is PodcastIndexPodcastsSource


def test_radiobrowser_map_row_schema():
    src = RadioBrowserStationsSource()
    s = {
        "stationuuid": "abc-123",
        "name": "Radio X",
        "url": "http://stream.example.com",
        "url_resolved": "http://stream.example.com/resolved",
        "homepage": "http://example.com",
        "favicon": "http://example.com/fav.ico",
        "country": "Germany",
        "countrycode": "DE",
        "state": "",
        "language": "german",
        "languagecodes": "de,en",
        "tags": "rock,pop," + ",".join(f"t{i}" for i in range(25)),
        "codec": "MP3",
        "bitrate": 128,
        "hls": False,
        "votes": 10,
        "clickcount": 100,
        "clicktrend": 1,
        "lastcheckok": 1,
    }
    row = src.map_row(s)
    assert row["stationuuid"] == "abc-123"
    assert row["language_codes"] == ["de", "en"]
    assert len(row["tags"]) == 20
    assert row["entity_type"] == "radio_station"
    assert set(row) == {
        "stationuuid", "name", "url", "url_resolved", "homepage", "favicon",
        "country", "countrycode", "state", "language", "language_codes",
        "tags", "codec", "bitrate", "hls", "votes", "clickcount", "clicktrend",
        "last_check_ok", "entity_type",
    }


def test_radiobrowser_map_row_drops_stations_without_name():
    assert RadioBrowserStationsSource().map_row({"stationuuid": "x", "name": ""}) is None


def test_radiobrowser_fetch_stops_on_short_page():
    src = RadioBrowserStationsSource()
    src._base_url = "https://de1.api.radio-browser.info"
    src.throttle.wait = lambda: None

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"stationuuid": "1", "name": "A"}]

    class FakeSession:
        def get(self, *a, **kw):
            return FakeResp()

    src._session = FakeSession()
    rows, cursor = src.fetch(0)
    assert len(rows) == 1
    assert cursor is None


def test_audiodb_map_row_schema():
    src = AudioDBArtistsSource()
    a = {
        "idArtist": "111",
        "strArtist": "Nirvana",
        "strMusicBrainzID": "mb-x",
        "strArtistAlternate": None,
        "intFormedYear": "1987",
        "intBornYear": None,
        "intDiedYear": "1994",
        "strCountry": "United States",
        "strCountryCode": "US",
        "strStyle": "Grunge",
        "strGenre": "Rock",
        "strMood": "Angst",
        "strWebsite": "nirvana.com",
        "strFacebook": None,
        "strTwitter": None,
        "strBiographyEN": "x" * 700,
        "intMembers": "3",
        "strLabel": "DGC",
        "strGender": "Male",
        "strArtistLogo": None,
        "strArtistThumb": None,
        "strArtistBanner": None,
        "strArtistFanart": None,
    }
    row = src.map_row(a)
    assert row["adb_id"] == "111"
    assert row["name"] == "Nirvana"
    assert len(row["biography_en"]) == 600
    assert set(row) == {
        "adb_id", "mb_id", "name", "alternate_name", "formed_year", "born_year",
        "disbanded_year", "country", "country_code", "style", "genre", "mood",
        "website", "facebook", "twitter", "biography_en", "members", "label",
        "gender", "logo_url", "thumb_url", "banner_url", "fanart_url",
    }


def test_audiodb_map_row_drops_without_name_or_id():
    assert AudioDBArtistsSource().map_row({"idArtist": "1", "strArtist": ""}) is None
    assert AudioDBArtistsSource().map_row({"idArtist": None, "strArtist": "X"}) is None


def test_audiodb_fetch_seed_stage_seeds_queue(monkeypatch):
    src = AudioDBArtistsSource()
    src._html_get = lambda url: '<a href="/artist/111-nirvana">Nirvana</a><a href="/artist/222-pearl-jam">Pearl Jam</a>'
    rows, cursor = src.fetch({"stage": "seed", "queue": []})
    assert rows == []
    assert cursor == {"stage": "crawl", "queue": ["111", "222"]}


def test_audiodb_fetch_crawl_stage_pops_and_expands_queue(monkeypatch):
    src = AudioDBArtistsSource()
    src._api_get = lambda path, params: {"artists": [{"idArtist": "111", "strArtist": "Nirvana"}]}
    src._html_get = lambda url: '<a href="/artist/333-foo-fighters">Foo Fighters</a>'
    rows, cursor = src.fetch({"stage": "crawl", "queue": ["111"]})
    assert len(rows) == 1
    assert rows[0]["name"] == "Nirvana"
    assert cursor == {"stage": "crawl", "queue": ["333"]}


def test_audiodb_fetch_crawl_stage_finishes_without_fill():
    src = AudioDBArtistsSource()
    src.do_fill = False
    rows, cursor = src.fetch({"stage": "crawl", "queue": []})
    assert rows == []
    assert cursor is None


def test_audiodb_fetch_crawl_stage_moves_to_fill():
    src = AudioDBArtistsSource()
    src.do_fill = True
    rows, cursor = src.fetch({"stage": "crawl", "queue": []})
    assert rows == []
    assert cursor["stage"] == "fill"


def test_batch2_scrapers_are_registered():
    reg = all_sources()
    assert reg.get("musicbrainz_artists") is MusicBrainzArtistsSource
    assert reg.get("musicbrainz_releases") is MusicBrainzReleasesSource
    assert reg.get("anilist_anime") is AniListAnimeSource
    assert reg.get("metal_archives") is MetalArchivesSource
    assert reg.get("gutenberg_books") is GutenbergBooksSource
    assert reg.get("podcastindex_podcasts") is PodcastIndexPodcastsSource
    assert reg.get("radiobrowser_stations") is RadioBrowserStationsSource
    assert reg.get("audiodb_artists") is AudioDBArtistsSource
