"""HTTP cassette tests for the MusicBrainz provider (offline — requests patched)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from mediavocab.models.signals import Signals

from metadatarr.resolve.providers.musicbrainz import MusicBrainzProvider

_MB_RECORDING = {
    "id": "5b11f4ce-a62d-471e-81fc-a69a8278c7da",
    "score": 100,
    "title": "Stairway to Heaven",
    "length": 482000,
    "first-release-date": "1971-11-08",
    "artist-credit": [
        {
            "name": "Led Zeppelin",
            "artist": {
                "id": "678d88b2-87b0-403b-b63d-5da7465aecc3",
                "name": "Led Zeppelin",
                "sort-name": "Led Zeppelin",
            },
        }
    ],
    "releases": [
        {
            "id": "73c96ca4-bdcf-4a39-b813-9c5e0f79c5ab",
            "country": "GB",
            "date": "1971-11-08",
        }
    ],
}


def _make_response(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    if status_code >= 400:
        from requests import HTTPError
        resp.raise_for_status.side_effect = HTTPError(f"HTTP {status_code}")
    else:
        resp.raise_for_status = MagicMock()
    return resp


def test_happy_path():
    p = MusicBrainzProvider()
    payload = {"recordings": [_MB_RECORDING]}
    with patch("metadatarr.resolve.providers.musicbrainz._SESSION.get", return_value=_make_response(payload)):
        m = p.lookup(Signals(title="Stairway to Heaven", artist="Led Zeppelin"))
    assert m is not None
    assert m.external_ids.musicbrainz_recording == "5b11f4ce-a62d-471e-81fc-a69a8278c7da"
    assert m.external_ids.musicbrainz_artist == "678d88b2-87b0-403b-b63d-5da7465aecc3"


def test_no_match():
    p = MusicBrainzProvider()
    payload = {"recordings": []}
    with patch("metadatarr.resolve.providers.musicbrainz._SESSION.get", return_value=_make_response(payload)):
        m = p.lookup(Signals(title="Unknown Song", artist="Nobody"))
    assert m is None


def test_api_error():
    p = MusicBrainzProvider()
    from requests import RequestException
    with patch("metadatarr.resolve.providers.musicbrainz._SESSION.get", side_effect=RequestException("503 Service Unavailable")):
        m = p.lookup(Signals(title="Stairway to Heaven", artist="Led Zeppelin"))
    assert m is None
