# SPDX-License-Identifier: Apache-2.0
"""Parsing of TheAudioDB answers by the inline client."""
from __future__ import annotations

import subprocess
import sys

import pytest

from metadatarr.resolve.providers._audiodb_client import AudioDBClient


class _Response:
    def __init__(self, payload=None, status=200, bad_json=False):
        self._payload, self.status_code, self._bad_json = payload, status, bad_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class _Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        assert timeout == 10
        self.calls.append((url, params))
        return self.responses.pop(0)


def _client(*responses) -> AudioDBClient:
    client = AudioDBClient()
    client._session = _Session(*responses)
    return client


BASE = "https://www.theaudiodb.com/api/v1/json/123"
TRACK = {"idTrack": "11", "strTrack": "Song", "strArtist": "Band", "intDuration": "215000",
         "intTrackNumber": "3", "strMusicBrainzID": "mb-track"}
ARTIST = {"idArtist": "5", "strArtist": "Band", "intFormedYear": "1990", "strMusicBrainzID": "mb-artist"}
ALBUM = {"idAlbum": "9", "strAlbum": "Record", "intYearReleased": "1999", "strMusicBrainzID": "mb-album"}


def test_search_track_returns_every_row_and_converts_numbers():
    client = _client(_Response({"track": [TRACK, {**TRACK, "idTrack": "12", "intDuration": ""}]}))
    tracks = client.search_track("Band", "Song")
    assert [t.id for t in tracks] == ["11", "12"]
    assert tracks[0].duration_ms == 215000 and tracks[0].track_number == 3
    assert tracks[1].duration_ms is None
    assert client._session.calls == [(f"{BASE}/searchtrack.php", {"s": "Band", "t": "Song"})]


@pytest.mark.parametrize("response", [
    _Response({"track": None}), _Response({}), _Response({"track": "x"}), _Response(bad_json=True),
    _Response(status=500), _Response([TRACK]), _Response(None),
    _Response({"track": [TRACK]}, status=429),
])
def test_search_track_without_usable_answer_is_empty(response):
    assert _client(response).search_track("a", "b") == []


@pytest.mark.parametrize("method, path, key, row, field, value", [
    ("get_artist_by_mbid", "artist-mb.php", "artists", ARTIST, "name", "Band"),
    ("get_album_by_mbid", "album-mb.php", "album", ALBUM, "name", "Record"),
    ("get_track_by_mbid", "track-mb.php", "track", TRACK, "title", "Song"),
])
def test_lookup_by_mbid_returns_the_first_row(method, path, key, row, field, value):
    other = {k: (v + "-other") for k, v in row.items()}
    client = _client(_Response({key: [row, other]}))
    found = getattr(client, method)("some-mbid")
    assert getattr(found, field) == value
    assert client._session.calls == [(f"{BASE}/{path}", {"i": "some-mbid"})]


@pytest.mark.parametrize("method, key", [
    ("get_artist_by_mbid", "artists"), ("get_album_by_mbid", "album"), ("get_track_by_mbid", "track"),
])
@pytest.mark.parametrize("response", [
    _Response({}), _Response(bad_json=True), _Response(status=404), _Response(None), _Response([]),
])
def test_lookup_by_mbid_without_usable_answer_is_none(method, key, response):
    assert getattr(_client(response), method)("x") is None


def test_lookup_by_mbid_with_null_rows_is_none():
    assert _client(_Response({"artists": None})).get_artist_by_mbid("x") is None


def test_row_the_model_rejects_raises():
    with pytest.raises(Exception):
        _client(_Response({"track": [{"strTrack": "no id"}]})).search_track("a", "b")


def test_provider_imports_without_the_pyaudiodb_package():
    code = ("import sys; sys.modules['pyaudiodb'] = None; "
            "import metadatarr.resolve.providers.audiodb; "
            "from metadatarr.resolve import all_providers; "
            "assert all_providers()['audiodb'].is_available()")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
