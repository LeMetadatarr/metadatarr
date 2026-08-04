"""Client tests with monkeypatched HTTP — no network."""
from typing import Any

import pytest

from metadatarr import (
    ArrMetadataClient,
    BookInfoClient,
    OpenLibraryClient,
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
    _patch_get(monkeypatch, "requests.sessions.Session.get", payload)

    client = ArrMetadataClient()
    series = client.search_series("The Boys")
    assert len(series) == 1
    assert series[0].tvdb_id == 355567


def test_arr_search_movie_handles_non_list(monkeypatch):
    _patch_get(monkeypatch, "requests.sessions.Session.get", {"error": "x"})

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
    _patch_get(monkeypatch, "requests.sessions.Session.get", payload)

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
    _patch_get(monkeypatch, "requests.sessions.Session.get", payload)

    bi = BookInfoClient.goodreads()
    hits = bi.search("hobbit")
    assert hits and hits[0].author_id == 3

# NOTE: AudioDBClient and TVmazeClient were extracted into the dedicated
# ``pyaudiodb`` / ``pytvmaze`` packages; their client tests now live in those
# repos. metadatarr's resolver consumes them via the providers (see
# tests/test_enrich.py, tests/test_provider_error_contract.py).
