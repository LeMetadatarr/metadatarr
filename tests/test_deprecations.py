"""Deprecated-but-kept public surface: ``search`` still works, but warns and
is no longer advertised via ``metadatarr.resolve.__all__``.
"""
from __future__ import annotations

import warnings

from mediavocab import MediaType
from mediavocab.models.signals import Signals

import metadatarr.resolve as mr_resolve
from metadatarr.resolve.base import search


def test_search_still_callable_and_matches_candidates():
    from metadatarr.resolve.base import candidates

    signals = Signals(title="Nonexistent Test Title XYZ", medium=MediaType.MOVIE)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        searched = search(signals)
    direct = candidates(signals)
    assert [m.provider for m in searched] == [m.provider for m in direct]


def test_search_emits_deprecation_warning():
    signals = Signals(title="Nonexistent Test Title XYZ", medium=MediaType.MOVIE)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        search(signals)
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    assert any("search" in str(w.message) for w in caught)


def test_search_not_in_resolve_all():
    assert "search" not in mr_resolve.__all__


def test_search_still_importable_from_resolve_package():
    # import still works even though it's dropped from __all__
    assert callable(mr_resolve.search)
