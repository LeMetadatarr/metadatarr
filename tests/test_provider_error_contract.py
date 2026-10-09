"""Providers swallow transport errors and return None (never raise).

Verifies the standardized error contract on the providers that fan out through
metadatarr's own requests-based clients: a ``requests.RequestException`` from the
client is logged and turned into ``None``; an unexpected exception is logged with
a stacktrace and also turned into ``None``. Either way, ``lookup`` never raises.
"""
from __future__ import annotations

import requests

from mediavocab import MediaType
from mediavocab.models.signals import Signals

from metadatarr.resolve.providers.openlibrary import OpenLibraryProvider
from metadatarr.resolve.providers.dvdcompare import DVDCompareProvider
from metadatarr.resolve.providers.audiodb import AudioDBProvider
from metadatarr.resolve.providers.servarr_proxy import ServarrProxyProvider


class _Boom:
    """Stub client whose every attribute raises the given exception."""

    def __init__(self, exc):
        self._exc = exc

    def __getattr__(self, _name):
        def _raise(*args, **kwargs):
            raise self._exc
        return _raise


def test_openlibrary_swallows_request_exception():
    p = OpenLibraryProvider()
    p._client = _Boom(requests.ConnectionError("down"))
    assert p.lookup(Signals(title="Dune", medium=MediaType.BOOK)) is None


def test_openlibrary_swallows_unexpected_exception():
    p = OpenLibraryProvider()
    p._client = _Boom(ValueError("bug"))
    assert p.lookup(Signals(title="Dune", medium=MediaType.BOOK)) is None


def test_dvdcompare_swallows_request_exception():
    p = DVDCompareProvider()
    p._client = _Boom(requests.Timeout("slow"))
    assert p.lookup(Signals(title="Alien", medium=MediaType.MOVIE)) is None


def test_dvdcompare_swallows_unexpected_exception():
    p = DVDCompareProvider()
    p._client = _Boom(KeyError("bug"))
    assert p.lookup(Signals(title="Alien", medium=MediaType.MOVIE)) is None


def test_audiodb_swallows_request_exception():
    p = AudioDBProvider()
    p._client = _Boom(requests.ConnectionError("down"))
    assert p.lookup(Signals(title="One", artist="Metallica",
                            medium=MediaType.MUSIC)) is None


def test_servarr_proxy_swallows_request_exception():
    p = ServarrProxyProvider()
    p._client = _Boom(requests.ConnectionError("down"))
    assert p.lookup(Signals(title="Inception", medium=MediaType.MOVIE)) is None


def test_servarr_proxy_swallows_unexpected_exception():
    p = ServarrProxyProvider()
    p._client = _Boom(RuntimeError("bug"))
    assert p.lookup(Signals(title="Inception", medium=MediaType.MOVIE)) is None
