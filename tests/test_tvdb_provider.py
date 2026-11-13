"""Tests for the TVDB provider (offline — transport is patched)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from mediavocab.models.signals import Signals

import metadatarr.resolve.providers.tvdb as tvdb_module
from metadatarr.resolve.providers.tvdb import TVDBProvider


def _make_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"data": data}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


def _session(get_return=None, get_side_effect=None):
    sess = MagicMock()
    if get_side_effect is not None:
        sess.get.side_effect = get_side_effect
    else:
        sess.get.return_value = get_return
    return sess


def test_exact_match_high_confidence():
    p = TVDBProvider()
    tvdb_module._token = "fake-token"
    result = {"tvdb_id": 121361, "name": "Breaking Bad", "year": "2008", "slug": "breaking-bad"}
    with patch.object(tvdb_module, "_http", return_value=_session(get_return=_make_response([result]))):
        m = p.lookup(Signals(title="Breaking Bad", year=2008))
    assert m is not None
    assert m.confidence >= 0.90
    assert m.external_ids.extra["tvdb_id"] == 121361
    assert "breaking-bad" in m.external_ids.extra["tvdb_url"]


def test_no_api_key_not_available():
    env = {k: v for k, v in os.environ.items() if k != "TVDB_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        p = TVDBProvider()
        assert p.is_available() is False


def test_api_key_set_available():
    with patch.dict(os.environ, {"TVDB_API_KEY": "somekey"}):
        p = TVDBProvider()
        assert p.is_available() is True


def test_no_results_returns_none():
    p = TVDBProvider()
    tvdb_module._token = "fake-token"
    with patch.object(tvdb_module, "_http", return_value=_session(get_return=_make_response([]))):
        m = p.lookup(Signals(title="NonExistentShow12345"))
    assert m is None


def test_exception_returns_none():
    p = TVDBProvider()
    tvdb_module._token = "fake-token"
    with patch.object(tvdb_module, "_http", return_value=_session(get_side_effect=Exception("network error"))):
        m = p.lookup(Signals(title="Breaking Bad"))
    assert m is None
