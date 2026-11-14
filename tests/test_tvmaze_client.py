# SPDX-License-Identifier: Apache-2.0
"""Parsing of the TVmaze API answers by the inline client."""
from __future__ import annotations

import subprocess
import sys

import pytest

from metadatarr.resolve.providers._tvmaze_client import TVmazeClient


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


def _client(*responses) -> TVmazeClient:
    client = TVmazeClient()
    client._session = _Session(*responses)
    return client


SHOW = {"id": 7, "name": "The Boys", "url": "https://www.tvmaze.com/shows/7", "premiered": "2019-07-26",
        "externals": {"thetvdb": 355567, "imdb": "tt1190634"}, "rating": {"average": 8.5},
        "image": {"medium": "m.jpg"}, "network": {"id": 1, "name": "Prime", "country": {"code": "US"}}}


def test_search_unwraps_the_score_envelope_in_order():
    other = {**SHOW, "id": 8, "name": "Other"}
    shows = _client(_Response([{"score": 1, "show": SHOW}, {"score": 0.5, "show": other}])).search_shows("boys")
    assert [s.id for s in shows] == [7, 8]
    assert shows[0].externals.imdb == "tt1190634" and shows[0].rating == 8.5
    assert shows[0].image_medium == "m.jpg" and shows[0].network.country_code == "US"


def test_search_sends_the_query():
    client = _client(_Response([]))
    client.search_shows("The Boys")
    assert client._session.calls == [("https://api.tvmaze.com/search/shows", {"q": "The Boys"})]


@pytest.mark.parametrize("response", [
    _Response([]), _Response({}), _Response({"show": SHOW}), _Response(None), _Response(bad_json=True),
    _Response(status=404),
    _Response([{"score": 1, "show": SHOW}], status=500),
])
def test_search_without_usable_answer_is_empty(response):
    assert _client(response).search_shows("x") == []


def test_search_skips_entries_without_a_show():
    shows = _client(_Response([{"score": 1}, "show", {"show": SHOW}])).search_shows("x")
    assert [s.id for s in shows] == [7]


def test_search_raises_for_a_show_the_model_rejects():
    with pytest.raises(Exception):
        _client(_Response([{"show": {"name": "no id"}}])).search_shows("x")


def test_lookup_by_thetvdb_sends_the_id_and_returns_the_show():
    client = _client(_Response(SHOW))
    show = client.lookup_by_thetvdb(355567)
    assert show.id == 7
    assert client._session.calls == [("https://api.tvmaze.com/lookup/shows", {"thetvdb": 355567})]


def test_lookup_by_imdb_sends_the_id():
    client = _client(_Response(SHOW))
    assert client.lookup_by_imdb("tt1190634").name == "The Boys"
    assert client._session.calls[0][1] == {"imdb": "tt1190634"}


@pytest.mark.parametrize("response", [
    _Response(status=404), _Response(status=500), _Response([SHOW]), _Response(None), _Response(bad_json=True),
])
def test_lookup_without_usable_answer_is_none(response):
    assert _client(response).lookup_by_imdb("tt1") is None


def test_provider_imports_without_the_pytvmaze_package():
    code = ("import sys; sys.modules['pytvmaze'] = None; "
            "import metadatarr.resolve.providers.tvmaze; "
            "from metadatarr.resolve import all_providers; "
            "assert all_providers()['tvmaze'].is_available()")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
