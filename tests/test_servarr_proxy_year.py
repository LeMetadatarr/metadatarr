"""servarr-proxy: search results must be disambiguated by query year.

Regression coverage for a resolver-quality bug found benchmarking against a
real movie library: Skyhook/Radarr-proxy search results are ordered by
popularity, not by relevance to the queried year, so same-title remakes and
originals (e.g. "Dawn of the Dead" 1978 vs 2004) collapsed to whichever is
more popular regardless of the year the caller asked for.
"""
from metadatarr.resolve import MediaType, Signals
from metadatarr.resolve.providers.servarr_proxy import (
    ServarrProxyProvider,
    _pick_by_year,
)
from metadatarr.models import RadarrMovie, SonarrSeries


def _movie(tmdb_id, year, title="Dawn of the Dead"):
    return RadarrMovie(title=title, year=year, tmdbId=tmdb_id)


def _series(tvdb_id, year, title="Evil Dead"):
    return SonarrSeries(title=title, year=year, tvdbId=tvdb_id)


DAWN_OF_THE_DEAD = [
    _movie(924, 2004),   # remake — most popular, listed first by Skyhook
    _movie(923, 1978),   # original
    _movie(555111, 2019),  # unrelated third result
]


# -----------------------------------------------------------------------------
# _pick_by_year unit coverage
# -----------------------------------------------------------------------------

def test_pick_by_year_exact_match():
    assert _pick_by_year(DAWN_OF_THE_DEAD, 1978).tmdb_id == 923


def test_pick_by_year_exact_match_other_year():
    assert _pick_by_year(DAWN_OF_THE_DEAD, 2004).tmdb_id == 924


def test_pick_by_year_none_falls_back_to_first_result():
    assert _pick_by_year(DAWN_OF_THE_DEAD, None) is DAWN_OF_THE_DEAD[0]


def test_pick_by_year_near_neighbor_within_one_year():
    results = [_movie(1, 2003), _movie(2, 1979)]
    # want 1978: no exact match, but 1979 is within +/-1
    assert _pick_by_year(results, 1978).tmdb_id == 2


def test_pick_by_year_no_year_bearing_results_falls_back_to_first():
    results = [_movie(1, None), _movie(2, None)]
    assert _pick_by_year(results, 1978) is results[0]


def test_pick_by_year_single_result():
    results = [_movie(42, 2010)]
    assert _pick_by_year(results, 1999).tmdb_id == 42


# -----------------------------------------------------------------------------
# _lookup_movie via the provider
# -----------------------------------------------------------------------------

def test_lookup_movie_picks_year_correct_original(monkeypatch):
    p = ServarrProxyProvider()
    monkeypatch.setattr(p._client, "search_movie", lambda term: DAWN_OF_THE_DEAD)

    match = p._lookup_movie(Signals(title="Dawn of the Dead", year=1978,
                                    medium=MediaType.MOVIE))
    assert match.external_ids.tmdb_movie == 923


def test_lookup_movie_picks_year_correct_remake(monkeypatch):
    p = ServarrProxyProvider()
    monkeypatch.setattr(p._client, "search_movie", lambda term: DAWN_OF_THE_DEAD)

    match = p._lookup_movie(Signals(title="Dawn of the Dead", year=2004,
                                    medium=MediaType.MOVIE))
    assert match.external_ids.tmdb_movie == 924


def test_lookup_movie_no_year_keeps_backcompat_first_result(monkeypatch):
    p = ServarrProxyProvider()
    monkeypatch.setattr(p._client, "search_movie", lambda term: DAWN_OF_THE_DEAD)

    match = p._lookup_movie(Signals(title="Dawn of the Dead", medium=MediaType.MOVIE))
    assert match.external_ids.tmdb_movie == 924


def test_lookup_movie_single_result_regression(monkeypatch):
    p = ServarrProxyProvider()
    monkeypatch.setattr(p._client, "search_movie", lambda term: [_movie(1, 2010)])

    match = p._lookup_movie(Signals(title="Whatever", year=1999, medium=MediaType.MOVIE))
    assert match.external_ids.tmdb_movie == 1


# -----------------------------------------------------------------------------
# _lookup_tv via the provider
# -----------------------------------------------------------------------------

EVIL_DEAD_SERIES = [
    _series(1, 2022, title="Evil Dead Rise"),
    _series(2, 1981, title="Evil Dead"),
]


def test_lookup_tv_picks_year_correct_result(monkeypatch):
    p = ServarrProxyProvider()
    monkeypatch.setattr(p._client, "search_series", lambda term: EVIL_DEAD_SERIES)

    match = p._lookup_tv(Signals(title="Evil Dead", year=1981,
                                 medium=MediaType.EPISODIC_SERIES))
    assert match.external_ids.tvdb == 2


def test_lookup_tv_no_year_keeps_backcompat_first_result(monkeypatch):
    p = ServarrProxyProvider()
    monkeypatch.setattr(p._client, "search_series", lambda term: EVIL_DEAD_SERIES)

    match = p._lookup_tv(Signals(title="Evil Dead", medium=MediaType.EPISODIC_SERIES))
    assert match.external_ids.tvdb == 1
