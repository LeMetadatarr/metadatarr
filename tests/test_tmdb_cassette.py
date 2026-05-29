"""HTTP cassette tests for the TMDB provider (offline — requests patched)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from mediavocab.models.signals import Signals

from metadatarr.resolve.providers.tmdb import TMDBProvider

_TMDB_MOVIE = {
    "id": 27205,
    "title": "Inception",
    "release_date": "2010-07-16",
    "original_language": "en",
    "vote_average": 8.3,
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


def test_movie_match():
    p = TMDBProvider()
    payload = {"results": [_TMDB_MOVIE], "total_results": 1}
    with patch.dict(os.environ, {"TMDB_API_KEY": "fake-key"}):
        with patch("requests.get", return_value=_make_response(payload)):
            m = p.lookup(Signals(title="Inception", year=2010))
    assert m is not None
    assert m.external_ids.tmdb_movie == 27205


def test_no_api_key():
    env = {k: v for k, v in os.environ.items() if k != "TMDB_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        p = TMDBProvider()
        assert p.is_available() is False


def test_no_results():
    p = TMDBProvider()
    payload = {"results": [], "total_results": 0}
    with patch.dict(os.environ, {"TMDB_API_KEY": "fake-key"}):
        with patch("requests.get", return_value=_make_response(payload)):
            m = p.lookup(Signals(title="NonExistentMovie99999"))
    assert m is None
