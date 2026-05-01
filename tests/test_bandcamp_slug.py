"""Bandcamp slug derivation — pure function, no network."""
from metadatarr.resolve.providers.bandcamp import derive_track_url, slugify_title


def test_slug_drops_apostrophes_and_lowercases():
    assert slugify_title("Don't Explain") == "dont-explain"


def test_slug_collapses_whitespace_and_underscores():
    assert slugify_title("  Nuclear   Chill  ") == "nuclear-chill"
    assert slugify_title("hello_world") == "hello-world"


def test_slug_drops_punctuation_keeps_digits():
    assert slugify_title("Track #3 (Live)") == "track-3-live"


def test_slug_collapses_runs_of_dashes():
    assert slugify_title("a -- b") == "a-b"


def test_slug_empty_for_empty_input():
    assert slugify_title("") == ""
    assert slugify_title("!!!") == ""


def test_derive_track_url_appends_to_artist_path():
    url = derive_track_url("https://piratech.bandcamp.com/", "Nuclear Chill")
    assert url == "https://piratech.bandcamp.com/track/nuclear-chill"


def test_derive_track_url_handles_missing_trailing_slash():
    url = derive_track_url("https://piratech.bandcamp.com", "Don't Explain")
    assert url == "https://piratech.bandcamp.com/track/dont-explain"


def test_derive_track_url_returns_none_on_empty_inputs():
    assert derive_track_url("", "x") is None
    assert derive_track_url("https://x.bandcamp.com/", "") is None
    assert derive_track_url("https://x.bandcamp.com/", "!!!") is None
