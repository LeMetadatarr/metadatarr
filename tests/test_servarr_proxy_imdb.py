"""servarr-proxy: movie lookups carry the IMDb id the Radarr proxy returns.

The fixtures are recorded ``radarrapi.servarr.com/v1/search?q=<title>``
responses (first five results each) for short films whose TMDB and IMDb ids
come from a real library.
"""
import json
from pathlib import Path

import pytest

from metadatarr.models import RadarrMovie
from metadatarr.resolve import MediaType, Signals
from metadatarr.resolve.providers.servarr_proxy import ServarrProxyProvider

FIXTURES = Path(__file__).parent / "fixtures" / "radarr"

CASES = [
    ("A Killer Secret", 2021, "a_killer_secret", 956490, "tt10374704"),
    ("Auroras", 2015, "auroras", 452132, "tt2766788"),
    ("Apotemnofilia", 2023, "apotemnofilia", 1181769, "tt28686754"),
    ("Bad Acid", 2022, "bad_acid", 1004423, "tt15527070"),
]


def _search(name):
    raw = json.loads((FIXTURES / f"search_{name}.json").read_text())
    return [RadarrMovie.model_validate(item) for item in raw]


@pytest.mark.parametrize("title,year,fixture,tmdb,imdb", CASES)
def test_lookup_movie_emits_imdb(monkeypatch, title, year, fixture, tmdb, imdb):
    p = ServarrProxyProvider()
    monkeypatch.setattr(p._client, "search_movie", lambda term: _search(fixture))
    match = p._lookup_movie(Signals(title=title, year=year, medium=MediaType.MOVIE))
    assert match.external_ids.tmdb_movie == tmdb
    assert match.external_ids.imdb == imdb


def test_missing_imdb_id_stays_none():
    movie = RadarrMovie.model_validate({"TmdbId": 1, "Title": "x", "ImdbId": None})
    assert movie.imdb_id is None


def test_malformed_imdb_id_is_dropped():
    movie = RadarrMovie.model_validate({"TmdbId": 1, "Title": "x", "ImdbId": "garbage"})
    assert movie.imdb_id is None
    assert RadarrMovie.model_validate({"TmdbId": 1, "Title": "x", "ImdbId": ""}).imdb_id is None


def test_lookup_movie_without_imdb(monkeypatch):
    p = ServarrProxyProvider()
    monkeypatch.setattr(p._client, "search_movie",
                        lambda term: [RadarrMovie(title="Foo", year=2020, tmdbId=5)])
    match = p._lookup_movie(Signals(title="Foo", year=2020, medium=MediaType.MOVIE))
    assert match.external_ids.tmdb_movie == 5
    assert match.external_ids.imdb is None
