"""Client tests with monkeypatched HTTP — no network."""
from typing import Any

import pytest

from metadatarr import (
    ArrMetadataClient,
    AudioDBClient,
    BookInfoClient,
    OpenLibraryClient,
    TVmazeClient,
)


class _FakeResponse:
    def __init__(self, payload: Any, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.content = b"x" if payload is not None else b""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _patch_get(monkeypatch, target, payload, status=200):
    def fake_get(*_args, **_kwargs):
        return _FakeResponse(payload, status=status)

    monkeypatch.setattr(target, fake_get)


def test_arr_search_series(monkeypatch):
    payload = [{"title": "The Boys", "tvdbId": 355567, "year": 2019}]
    _patch_get(monkeypatch, "metadatarr.client.requests.get", payload)

    client = ArrMetadataClient()
    series = client.search_series("The Boys")
    assert len(series) == 1
    assert series[0].tvdb_id == 355567


def test_arr_search_movie_handles_non_list(monkeypatch):
    _patch_get(monkeypatch, "metadatarr.client.requests.get", {"error": "x"})

    client = ArrMetadataClient()
    assert client.search_movie("nope") == []


def test_openlibrary_search(monkeypatch):
    payload = {
        "numFound": 1,
        "docs": [{
            "key": "/works/OL27482W",
            "title": "The Hobbit",
            "author_name": ["J. R. R. Tolkien"],
            "cover_i": 1,
        }],
    }
    _patch_get(monkeypatch, "metadatarr.client.requests.get", payload)

    client = OpenLibraryClient()
    hits = client.search("hobbit")
    assert len(hits) == 1
    assert hits[0].work_key == "/works/OL27482W"


def test_openlibrary_cover_url():
    assert OpenLibraryClient.cover_url(123) == "https://covers.openlibrary.org/b/id/123-L.jpg"
    assert OpenLibraryClient.cover_url(123, "s").endswith("123-S.jpg")
    # invalid size falls back to L
    assert OpenLibraryClient.cover_url(123, "XL").endswith("123-L.jpg")


def test_bookinfo_search(monkeypatch):
    payload = [{"bookId": 1, "workId": 2, "author": {"id": 3}}]
    _patch_get(monkeypatch, "metadatarr.client.requests.get", payload)

    bi = BookInfoClient.goodreads()
    hits = bi.search("hobbit")
    assert hits and hits[0].author_id == 3


def test_audiodb_search_artist(monkeypatch):
    payload = {"artists": [{"idArtist": "111", "strArtist": "Daft Punk"}]}
    monkeypatch.setattr(
        "requests.Session.get",
        lambda self, url, **kw: _FakeResponse(payload),
    )

    client = AudioDBClient()
    artists = client.search_artist("Daft Punk")
    assert len(artists) == 1
    assert artists[0].id == "111"


def test_audiodb_handles_no_artists(monkeypatch):
    payload = {"artists": None}
    monkeypatch.setattr(
        "requests.Session.get",
        lambda self, url, **kw: _FakeResponse(payload),
    )
    assert AudioDBClient().search_artist("nope") == []


def test_tvmaze_singlesearch(monkeypatch):
    payload = {"id": 1, "name": "The Boys", "type": "Scripted"}
    monkeypatch.setattr(
        "requests.Session.get",
        lambda self, url, **kw: _FakeResponse(payload),
    )

    show = TVmazeClient().singlesearch("The Boys")
    assert show is not None
    assert show.id == 1
    assert show.show_type == "Scripted"


def test_tvmaze_search_shows_unwraps(monkeypatch):
    payload = [{"score": 0.9, "show": {"id": 1, "name": "X"}}]
    monkeypatch.setattr(
        "requests.Session.get",
        lambda self, url, **kw: _FakeResponse(payload),
    )
    out = TVmazeClient().search_shows("X")
    assert len(out) == 1
    assert out[0].id == 1
