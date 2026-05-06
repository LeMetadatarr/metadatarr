"""Signal comparison and merging."""
from metadatarr.resolve import (
    MediaType,
    Signals,
    compare,
    match_quality,
    merged,
    signal_hash,
)


def test_compare_no_overlap_is_match():
    a = Signals(title="Inception")
    b = Signals(year=2010)
    assert compare(a, b) == []


def test_compare_year_within_tolerance():
    assert compare(Signals(year=2010), Signals(year=2011)) == []


def test_compare_year_outside_tolerance_conflicts():
    out = compare(Signals(year=2010), Signals(year=2015))
    assert len(out) == 1
    assert out[0].signal == "year"


def test_compare_medium_mismatch():
    out = compare(Signals(medium=MediaType.MOVIE), Signals(medium=MediaType.TV))
    assert any(c.signal == "medium" for c in out)


def test_compare_season_and_episode_mismatch():
    out = compare(Signals(season=1, episode=1), Signals(season=2, episode=1))
    assert any(c.signal == "season" for c in out)

    out = compare(Signals(season=1, episode=1), Signals(season=1, episode=4))
    assert any(c.signal == "episode" for c in out)


def test_compare_runtime_uses_medium_tolerance():
    # Two episode runtimes 25s apart — inside the 30s EPISODIC_SERIES window,
    # outside the 5s default — must NOT register a conflict. (TV is now
    # reserved for live-broadcast channels with 0s tolerance.)
    a = Signals(runtime=2400.0, medium=MediaType.EPISODIC_SERIES)
    b = Signals(runtime=2425.0, medium=MediaType.EPISODIC_SERIES)
    assert compare(a, b) == []
    # Same gap between music tracks → conflict.
    a = Signals(runtime=200.0, medium=MediaType.MUSIC)
    b = Signals(runtime=225.0, medium=MediaType.MUSIC)
    assert any(c.signal == "runtime" for c in compare(a, b))


def test_compare_diacritics_folded():
    """`café` and `cafe` should not register as a conflict."""
    assert compare(Signals(title="Café"), Signals(title="cafe")) == []
    assert compare(Signals(title="Pokémon"), Signals(title="Pokemon")) == []


def test_compare_fuzzy_title_match():
    # different punctuation / casing shouldn't trip the fuzzy threshold
    assert compare(Signals(title="The Boys"), Signals(title="the boys")) == []


def test_merged_first_non_none_wins():
    a = Signals(title="A", year=2010)
    b = Signals(title="B", artist="x")
    out = merged(a, b)
    assert out.title == "A"
    assert out.year == 2010
    assert out.artist == "x"


def test_match_quality_perfect_when_signals_align():
    a = Signals(title="Inception", year=2010, medium=MediaType.MOVIE)
    b = Signals(title="Inception", year=2010, medium=MediaType.MOVIE)
    assert match_quality(a, b) == 1.0


def test_match_quality_drops_on_year_mismatch():
    a = Signals(title="Inception", year=2010, medium=MediaType.MOVIE)
    b = Signals(title="Inception", year=2020, medium=MediaType.MOVIE)
    score = match_quality(a, b)
    assert score < 0.6  # halved by year mismatch


def test_match_quality_drops_on_medium_mismatch():
    a = Signals(title="X", medium=MediaType.MOVIE)
    b = Signals(title="X", medium=MediaType.TV)
    assert match_quality(a, b) == 0.5


def test_match_quality_handles_missing_fields_gracefully():
    a = Signals()
    b = Signals(title="X")
    assert match_quality(a, b) == 1.0


def test_match_quality_drops_on_title_drift():
    a = Signals(title="Inception")
    b = Signals(title="Interstellar")
    assert match_quality(a, b) < 0.7


def test_signal_hash_is_stable():
    s = Signals(title="Inception", year=2010)
    assert signal_hash(s) == signal_hash(s)
