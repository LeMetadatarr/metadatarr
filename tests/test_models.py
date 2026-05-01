"""Pydantic model alias / parsing checks."""
from metadatarr.models import (
    AnnasArchiveBook,
    AudioDBArtist,
    BookInfoSearchHit,
    LidarrArtist,
    OpenLibrarySearchHit,
    RadarrMovie,
    SonarrSeries,
    TVmazeShow,
)


def test_sonarr_series_aliases():
    s = SonarrSeries.model_validate({"title": "The Boys", "tvdbId": 355567, "year": 2019})
    assert s.title == "The Boys"
    assert s.tvdb_id == 355567
    assert s.year == 2019


def test_radarr_movie_aliases_camel_and_pascal():
    s = RadarrMovie.model_validate({"Title": "Inception", "TmdbId": 27205, "Year": 2010})
    assert s.title == "Inception"
    assert s.tmdb_id == 27205
    assert s.year == 2010


def test_lidarr_artist_pascal_path():
    s = LidarrArtist.model_validate({
        "ArtistName": "Daft Punk",
        "Artist": {"Id": "abc", "ArtistName": "Daft Punk"},
    })
    assert s.id == "abc"
    assert s.name == "Daft Punk"


def test_bookinfo_search_hit():
    s = BookInfoSearchHit.model_validate({"bookId": 1, "workId": 2, "author": {"id": 3}})
    assert s.book_id == 1
    assert s.work_id == 2
    assert s.author_id == 3


def test_openlibrary_search_hit():
    s = OpenLibrarySearchHit.model_validate({
        "key": "/works/OL27482W",
        "title": "The Hobbit",
        "author_name": ["J. R. R. Tolkien"],
        "cover_i": 12345,
    })
    assert s.work_key == "/works/OL27482W"
    assert s.author_names == ["J. R. R. Tolkien"]
    assert s.cover_id == 12345


def test_annas_archive_book():
    b = AnnasArchiveBook(title="x", author="y", formats="EPUB", md5="deadbeef")
    assert b.title == "x"
    assert b.formats == "EPUB"


def test_audiodb_artist_aliases():
    a = AudioDBArtist.model_validate({"idArtist": "111", "strArtist": "Daft Punk", "intFormedYear": 1993})
    assert a.id == "111"
    assert a.name == "Daft Punk"
    assert a.formed_year == 1993


def test_tvmaze_show_aliases():
    s = TVmazeShow.model_validate({
        "id": 1,
        "name": "The Boys",
        "type": "Scripted",
        "averageRuntime": 60,
        "officialSite": "https://example.com",
    })
    assert s.show_type == "Scripted"
    assert s.average_runtime == 60
    assert s.official_site == "https://example.com"
