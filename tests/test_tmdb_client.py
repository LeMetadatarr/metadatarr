# SPDX-License-Identifier: Apache-2.0
"""Parsing of TMDB answers and the best-match choice of the inline client."""
from __future__ import annotations

import subprocess
import sys

import pytest

from metadatarr.resolve.providers._tmdb_client import TMDBClient, TMDBMovie


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

    def get(self, url, params=None, timeout=None):
        assert timeout == 20
        self.calls.append((url, params))
        return self.responses.pop(0)


def _client(*responses, key="k") -> TMDBClient:
    return TMDBClient(key, _Session(*responses))


def _movie(id, title, date="2010-07-16"):
    return {"id": id, "title": title, "release_date": date, "overview": "ignored"}


def _results(*movies):
    return _Response({"results": list(movies)})


def test_search_sends_key_query_and_page():
    client = _client(_results())
    client.search_movie("Inception", page=2)
    assert client._session.calls == [("https://api.themoviedb.org/3/search/movie",
                                      {"query": "Inception", "page": 2, "api_key": "k"})]


def test_search_keeps_relevance_order_and_skips_rejected_rows():
    movies = _client(_results(_movie(1, "A"), {"title": "no id"}, "junk", _movie(2, "B"))).search_movie("x")
    assert [m.id for m in movies] == [1, 2]


@pytest.mark.parametrize("response", [
    _Response({"results": None}), _Response({}), _Response({"results": "x"}), _Response(bad_json=True),
    _Response(status=401), _Response([_movie(1, "A")]), _Response(None),
    _Response({"results": [_movie(1, "A")]}, status=500),
])
def test_search_without_usable_answer_is_empty(response):
    assert _client(response).search_movie("x") == []


def test_search_without_a_key_makes_no_request():
    client = _client(key="")
    assert client.search_movie("x") == [] and client._session.calls == []


@pytest.mark.parametrize("date, year", [
    ("2010-07-16", 2010), ("2010", 2010), ("", None), (None, None), ("abc", None), ("20x0-01-01", None),
])
def test_movie_year(date, year):
    assert TMDBMovie(id=1, release_date=date).year == year


def test_exact_title_with_year_within_one_scores_095():
    movie, confidence = _client(_results(_movie(1, "Inception", "2011-01-01"))).best_match("inception", 2010)
    assert (movie.id, confidence) == (1, 0.95)


@pytest.mark.parametrize("year, date", [(None, "2010-01-01"), (2010, "2013-01-01"), (2010, None), (0, "2010-01-01")])
def test_exact_title_without_close_year_scores_085(year, date):
    _, confidence = _client(_results(_movie(1, "Inception", date))).best_match("Inception", year)
    assert confidence == 0.85


def test_year_two_apart_is_not_close():
    _, confidence = _client(_results(_movie(1, "Inception", "2012-01-01"))).best_match("Inception", 2010)
    assert confidence == 0.85


def test_year_one_apart_is_close():
    _, confidence = _client(_results(_movie(1, "Inception", "2009-01-01"))).best_match("Inception", 2010)
    assert confidence == 0.95


@pytest.mark.parametrize("title", ["Inception 2", "Inc"])
def test_substring_either_way_scores_060(title):
    _, confidence = _client(_results(_movie(1, title))).best_match("Inception")
    assert confidence == 0.60


def test_unrelated_title_scores_035():
    movie, confidence = _client(_results(_movie(1, "Heat"), _movie(2, "Ran"))).best_match("Inception")
    assert (movie.id, confidence) == (1, 0.35)


def test_best_score_wins_over_relevance_order_and_first_wins_ties():
    results = _results(_movie(1, "Heat"), _movie(2, "Inception 2"), _movie(3, "Inception"), _movie(4, "Inception"))
    movie, confidence = _client(results).best_match("Inception")
    assert (movie.id, confidence) == (3, 0.85)
    results = _results(_movie(5, "Inception 2"), _movie(6, "Inception 3"))
    assert _client(results).best_match("Inception")[0].id == 5


def test_no_results_gives_none():
    assert _client(_results()).best_match("x") is None


def test_missing_title_is_a_substring_match():
    movie, confidence = _client(_results({"id": 9})).best_match("x")
    assert (movie.id, confidence) == (9, 0.60)


def test_provider_imports_without_the_pytmdb_package():
    code = ("import sys; sys.modules['pytmdb'] = None; "
            "import metadatarr.resolve.providers.tmdb; "
            "from metadatarr.resolve import all_providers; "
            "assert 'tmdb' in all_providers()")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
