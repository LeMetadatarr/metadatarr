"""Deep client coverage — every public method, plus error paths."""
import pytest

from metadatarr import (
    AnnasArchiveClient,
    ArrMetadataClient,
    AudioDBClient,
    BookInfoClient,
    OpenLibraryClient,
    TVmazeClient,
)


class _Resp:
    def __init__(self, payload=None, status=200, content=b"x"):
        self._payload = payload
        self.status_code = status
        self.text = content.decode() if isinstance(content, bytes) else content
        self.content = content if isinstance(content, bytes) else content.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


# -----------------------------------------------------------------------------
# ArrMetadataClient — every method, plus exception path
# -----------------------------------------------------------------------------

def _patch_arr(monkeypatch, payload):
    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp(payload),
    )


def test_arr_get_series_info(monkeypatch):
    _patch_arr(monkeypatch, {"title": "X", "tvdbId": 1, "year": 2020})
    s = ArrMetadataClient().get_series_info(1)
    assert s and s.tvdb_id == 1


def test_arr_get_series_info_empty(monkeypatch):
    _patch_arr(monkeypatch, {})
    assert ArrMetadataClient().get_series_info(1) is None


def test_arr_get_movie_info(monkeypatch):
    _patch_arr(monkeypatch, {"title": "X", "tmdbId": 1})
    m = ArrMetadataClient().get_movie_info(1)
    assert m and m.tmdb_id == 1


def test_arr_get_artist_search_and_info(monkeypatch):
    _patch_arr(monkeypatch, [{"artistName": "Daft Punk", "artistId": "abc"}])
    artists = ArrMetadataClient().search_artist("Daft Punk")
    assert artists and artists[0].id == "abc"


def test_arr_get_artist_info(monkeypatch):
    _patch_arr(monkeypatch, {"artistName": "X", "artistId": "abc"})
    a = ArrMetadataClient().get_artist_info("abc")
    assert a and a.id == "abc"


def test_arr_get_artist_info_none(monkeypatch):
    _patch_arr(monkeypatch, {})
    assert ArrMetadataClient().get_artist_info("abc") is None


def test_arr_search_handles_request_failure(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("network")
    monkeypatch.setattr("metadatarr.client.requests.get", boom)
    assert ArrMetadataClient().search_series("x") == []
    assert ArrMetadataClient().get_movie_info(1) is None


# -----------------------------------------------------------------------------
# OpenLibraryClient — every method, including ISBN, edition, author, covers
# -----------------------------------------------------------------------------

def test_openlibrary_get_work(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp({
            "key": "/works/OL27482W",
            "title": "The Hobbit",
            "description": {"type": "/type/text", "value": "A fantasy novel."},
            "subjects": ["Fantasy"],
            "covers": [1],
            "first_publish_date": "1937",
            "authors": [{"author": {"key": "/authors/OL26320A"}}],
        }),
    )
    w = OpenLibraryClient().get_work("OL27482W")
    assert w is not None
    assert w.key == "OL27482W"
    assert w.description == "A fantasy novel."
    assert w.author_keys == ["OL26320A"]


def test_openlibrary_get_work_strips_prefix(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp({"key": "/works/OL1W", "title": "T"}),
    )
    # Pass with /works/ prefix — should still work
    w = OpenLibraryClient().get_work("/works/OL1W")
    assert w is not None and w.title == "T"


def test_openlibrary_get_edition(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp({
            "key": "/books/OL1M",
            "title": "Hobbit Edition",
            "isbn_10": ["1234567890"],
            "isbn_13": ["9781234567897"],
            "publishers": ["Acme"],
            "languages": [{"key": "/languages/eng"}],
            "works": [{"key": "/works/OL27482W"}],
            "number_of_pages": 300,
        }),
    )
    e = OpenLibraryClient().get_edition("OL1M")
    assert e is not None
    assert e.isbn_13 == ["9781234567897"]
    assert e.languages == ["eng"]
    assert e.work_keys == ["OL27482W"]


def test_openlibrary_get_edition_by_isbn(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp({"key": "/books/OL1M", "title": "T"}),
    )
    e = OpenLibraryClient().get_edition_by_isbn("9781234567897")
    assert e is not None and e.title == "T"


def test_openlibrary_get_author(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp({
            "key": "/authors/OL26320A",
            "name": "J. R. R. Tolkien",
            "personal_name": "John Ronald Reuel Tolkien",
            "bio": "...",
        }),
    )
    a = OpenLibraryClient().get_author("OL26320A")
    assert a is not None and a.name == "J. R. R. Tolkien"


def test_openlibrary_handles_failures(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("net")
    monkeypatch.setattr("metadatarr.client.requests.get", boom)
    c = OpenLibraryClient()
    assert c.search("x") == []
    assert c.get_work("X") is None
    assert c.get_edition("X") is None
    assert c.get_edition_by_isbn("0") is None
    assert c.get_author("X") is None


def test_openlibrary_search_non_dict(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp([1, 2, 3]),
    )
    assert OpenLibraryClient().search("x") == []


# -----------------------------------------------------------------------------
# BookInfoClient — work, book, author, and class methods
# -----------------------------------------------------------------------------

def test_bookinfo_classmethods():
    g = BookInfoClient.goodreads()
    h = BookInfoClient.hardcover()
    assert g.base_url == BookInfoClient.GOODREADS
    assert h.base_url == BookInfoClient.HARDCOVER


def test_bookinfo_get_work_book_author(monkeypatch):
    work_payload = {
        "ForeignId": 100, "Title": "T",
        "Books": [{"ForeignId": 1, "Title": "B1"}],
    }
    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp(work_payload),
    )
    bi = BookInfoClient.goodreads()
    w = bi.get_work(100)
    assert w and w.title == "T" and w.books[0].title == "B1"
    b = bi.get_book(1)
    assert b and b.title == "T"

    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp({"ForeignId": 5, "Name": "Tolkien"}),
    )
    a = bi.get_author(5)
    assert a and a.name == "Tolkien"


def test_bookinfo_handles_empty_and_errors(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp(None, content=b""),
    )
    bi = BookInfoClient.goodreads()
    assert bi.search("x") == []
    assert bi.get_work(1) is None

    def boom(*a, **kw):
        raise RuntimeError("net")
    monkeypatch.setattr("metadatarr.client.requests.get", boom)
    assert bi.get_book(1) is None
    assert bi.get_author(1) is None


# -----------------------------------------------------------------------------
# AnnasArchiveClient — HTML parsing happy path + failure modes
# -----------------------------------------------------------------------------

_AA_HTML = """
<html><body>
<table>
  <tr>
    <td><a tabindex="-1" href="/md5/abcdef1234567890"><img src="https://example.com/c.jpg"/></a></td>
    <td>The Hobbit</td>
    <td>J. R. R. Tolkien</td>
    <td>en</td>
    <td></td><td></td><td></td><td></td>
    <td>2.5 MB</td>
    <td>EPUB</td>
  </tr>
  <tr>
    <td><a tabindex="-1" href=""></a></td>
    <td>no md5</td>
    <td>x</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td>
  </tr>
</table>
</body></html>
"""


def test_annas_archive_parses_table(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp(content=_AA_HTML.encode()),
    )
    books = AnnasArchiveClient().search("hobbit")
    assert len(books) == 1
    b = books[0]
    assert b.md5 == "abcdef1234567890"
    assert b.formats == "EPUB"
    assert b.cover_url == "https://example.com/c.jpg"


def test_annas_archive_no_table(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp(content=b"<html><body>nothing</body></html>"),
    )
    assert AnnasArchiveClient().search("x") == []


def test_annas_archive_all_mirrors_fail(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("net")
    monkeypatch.setattr("metadatarr.client.requests.get", boom)
    assert AnnasArchiveClient(mirrors=["https://a", "https://b"]).search("x") == []


def test_annas_archive_non_2xx_skips(monkeypatch):
    monkeypatch.setattr(
        "metadatarr.client.requests.get",
        lambda *a, **kw: _Resp(content=b"err", status=503),
    )
    assert AnnasArchiveClient(mirrors=["https://a"]).search("x") == []


# -----------------------------------------------------------------------------
# AudioDBClient — search/get for artist, album, track + by-mbid
# -----------------------------------------------------------------------------

def _patch_session(monkeypatch, payload, status=200):
    def fake(self, url, **kw):
        return _Resp(payload, status=status)
    monkeypatch.setattr("requests.Session.get", fake)


def test_audiodb_artist_lookups(monkeypatch):
    payload = {"artists": [{"idArtist": "1", "strArtist": "X"}]}
    _patch_session(monkeypatch, payload)
    c = AudioDBClient()
    assert c.search_artist("x")[0].id == "1"
    assert c.get_artist("1").id == "1"
    assert c.get_artist_by_mbid("mbid").id == "1"


def test_audiodb_artist_missing(monkeypatch):
    _patch_session(monkeypatch, {"artists": None})
    c = AudioDBClient()
    assert c.get_artist("1") is None
    assert c.get_artist_by_mbid("m") is None


def test_audiodb_album_and_discography(monkeypatch):
    payload = {"album": [{"idAlbum": "1", "strAlbum": "A"}]}
    _patch_session(monkeypatch, payload)
    c = AudioDBClient()
    assert c.search_album("x")[0].id == "1"
    assert c.search_album("x", "y")[0].id == "1"
    assert c.get_album("1").id == "1"
    assert c.get_album_by_mbid("m").id == "1"
    assert c.discography("x")[0].id == "1"


def test_audiodb_album_missing(monkeypatch):
    _patch_session(monkeypatch, {"album": None})
    c = AudioDBClient()
    assert c.get_album("1") is None
    assert c.get_album_by_mbid("m") is None


def test_audiodb_track(monkeypatch):
    payload = {"track": [{"idTrack": "1", "strTrack": "T"}]}
    _patch_session(monkeypatch, payload)
    c = AudioDBClient()
    assert c.search_track("a", "t")[0].id == "1"
    assert c.get_track("1").id == "1"
    assert c.get_track_by_mbid("m").id == "1"


def test_audiodb_track_missing(monkeypatch):
    _patch_session(monkeypatch, {"track": None})
    c = AudioDBClient()
    assert c.get_track("1") is None
    assert c.get_track_by_mbid("m") is None


def test_audiodb_handles_request_error(monkeypatch):
    def boom(self, url, **kw):
        raise RuntimeError("net")
    monkeypatch.setattr("requests.Session.get", boom)
    assert AudioDBClient().search_artist("x") == []


# -----------------------------------------------------------------------------
# TVmazeClient — every method, including 404 path
# -----------------------------------------------------------------------------

def test_tvmaze_get_show(monkeypatch):
    _patch_session(monkeypatch, {"id": 1, "name": "X"})
    assert TVmazeClient().get_show(1).id == 1


def test_tvmaze_404_returns_none(monkeypatch):
    def fake(self, url, **kw):
        return _Resp(None, status=404)
    monkeypatch.setattr("requests.Session.get", fake)
    c = TVmazeClient()
    assert c.get_show(1) is None
    assert c.lookup_by_thetvdb(1) is None
    assert c.lookup_by_imdb("tt0") is None
    assert c.singlesearch("x") is None


def test_tvmaze_lookups(monkeypatch):
    _patch_session(monkeypatch, {"id": 7, "name": "Y"})
    c = TVmazeClient()
    assert c.lookup_by_thetvdb(123).id == 7
    assert c.lookup_by_imdb("tt0").id == 7


def test_tvmaze_seasons_and_cast_and_people(monkeypatch):
    _patch_session(monkeypatch, [
        {"id": 1, "number": 1, "episodeOrder": 8, "premiereDate": "2019-01-01"},
    ])
    assert TVmazeClient().get_seasons(1)[0].number == 1

    _patch_session(monkeypatch, [
        {"person": {"id": 1, "name": "P"}, "character": {"name": "C"}},
    ])
    cast = TVmazeClient().get_cast(1)
    assert cast and cast[0].character_name == "C"

    _patch_session(monkeypatch, [{"person": {"id": 1, "name": "P"}}])
    assert TVmazeClient().search_people("p")[0].id == 1


def test_tvmaze_collection_endpoints_handle_non_list(monkeypatch):
    _patch_session(monkeypatch, {"oops": "not a list"})
    c = TVmazeClient()
    assert c.search_shows("x") == []
    assert c.get_seasons(1) == []
    assert c.get_cast(1) == []
    assert c.search_people("x") == []
