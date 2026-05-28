"""Tests for the IAFD provider (offline — pyiafd network is patched)."""
from __future__ import annotations

from unittest.mock import patch

from mediavocab.models.signals import Signals

from metadatarr.resolve.providers.iafd import IAFDProvider


def _result(id="abc123", name="Debbie Does Dallas", url="https://www.iafd.com/title.rme/title=debbie-does-dallas/year=1978/debbie-does-dallas.htm", year="1978"):
    from pyiafd.models import SearchResult
    return SearchResult(id=id, name=name, url=url, kind="title", year=year)


def test_exact_match_high_confidence():
    p = IAFDProvider()
    r = _result(name="Debbie Does Dallas", year="1978")
    with patch("pyiafd.search.search_titles", return_value=[r]):
        m = p.lookup(Signals(title="Debbie Does Dallas", year=1978))
    assert m is not None
    assert m.confidence >= 0.90
    assert m.external_ids.extra["iafd_title_id"] == "abc123"
    assert "iafd.com" in m.external_ids.extra["iafd_title_url"]


def test_partial_match_lower_confidence():
    p = IAFDProvider()
    r = _result(name="Debbie Does Dallas Again")
    with patch("pyiafd.search.search_titles", return_value=[r]):
        m = p.lookup(Signals(title="Debbie Does Dallas"))
    assert m is not None
    assert m.confidence < 0.90


def test_no_results_returns_none():
    p = IAFDProvider()
    with patch("pyiafd.search.search_titles", return_value=[]):
        m = p.lookup(Signals(title="Debbie Does Dallas"))
    assert m is None


def test_exception_returns_none():
    p = IAFDProvider()
    with patch("pyiafd.search.search_titles", side_effect=Exception("network error")):
        m = p.lookup(Signals(title="Debbie Does Dallas"))
    assert m is None


def test_year_match_boosts_confidence():
    p = IAFDProvider()
    r = _result(name="Debbie Does Dallas", year="1978")
    with patch("pyiafd.search.search_titles", return_value=[r]):
        m = p.lookup(Signals(title="Debbie Does Dallas", year=1978))
    assert m is not None
    assert m.confidence >= 0.90


def test_empty_title_returns_none():
    p = IAFDProvider()
    m = p.lookup(Signals())
    assert m is None


def test_is_available():
    assert IAFDProvider().is_available() is True
