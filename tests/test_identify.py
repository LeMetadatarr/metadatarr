# SPDX-License-Identifier: Apache-2.0
"""Tests for metadatarr.identify — mocked xazam, no network, no real
fingerprinting.
"""
from __future__ import annotations

import io
import sys
from types import ModuleType
from unittest import mock

import pytest

from mediavocab import MediaType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals

from metadatarr.identify import AudioIdentifyError, identify_audio
from metadatarr.resolve.base import ResolveResult


class _FakeTrack:
    key = "12345"
    title = "Never Gonna Give You Up"
    subtitle = "Rick Astley"
    url = "https://shazam.example/track/12345"

    @property
    def images(self):
        raise AssertionError("unused")

    @property
    def cover_art(self):
        return "https://shazam.example/art.jpg"

    @property
    def apple_music_url(self):
        return "https://music.apple.com/track/12345"

    @property
    def spotify_uri(self):
        return "spotify:track:abc123"

    @property
    def deezer_uri(self):
        return ""

    @property
    def metadata_table(self):
        return {"Album": "Whenever You Need Somebody", "ISRC": "GBARL8600001"}


class _FakeResult:
    def __init__(self, matched):
        self._matched = matched
        self.track = _FakeTrack() if matched else None

    @property
    def matched(self):
        return self._matched


class _FakeClient:
    def __init__(self, transport):
        self._transport = transport

    async def identify(self, audio_bytes):
        return _FakeResult(matched=True)


class _FakeTransport:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _install_fake_xazam():
    mod = ModuleType("xazam")
    mod.ShazamClient = _FakeClient
    mod.ShazamTransport = _FakeTransport
    sys.modules["xazam"] = mod
    return mod


@pytest.fixture()
def fake_xazam():
    mod = _install_fake_xazam()
    yield mod
    sys.modules.pop("xazam", None)


@pytest.fixture()
def no_xazam():
    sys.modules.pop("xazam", None)
    # Force ImportError even if xazam happens to be installed for real.
    with mock.patch.dict(sys.modules, {"xazam": None}):
        yield


def _fake_resolve_result():
    return ResolveResult(
        signals=Signals(title="Never Gonna Give You Up", artist="Rick Astley",
                        medium=MediaType.MUSIC),
        external_ids=ExternalIds(musicbrainz_recording="abc-123-mbid"),
    )


def test_identify_audio_matched_builds_signals_and_calls_enrich(fake_xazam):
    with mock.patch("metadatarr.identify.run_resolve", return_value=_fake_resolve_result()) as m_resolve, \
         mock.patch("metadatarr.identify.run_enrich",
                    return_value=ExternalIds(discogs_release=999)) as m_enrich:
        match = identify_audio(b"fake-audio-bytes")

    assert match.matched is True
    assert match.title == "Never Gonna Give You Up"
    assert match.artist == "Rick Astley"
    assert match.album == "Whenever You Need Somebody"
    assert match.isrc == "GBARL8600001"
    assert match.signals.title == "Never Gonna Give You Up"
    assert match.signals.medium == MediaType.MUSIC

    m_resolve.assert_called_once()
    m_enrich.assert_called_once()

    # raw Shazam ids preserved in `.extra`
    assert match.external_ids.extra.get("isrc") == "GBARL8600001"
    assert match.external_ids.extra.get("shazam_key") == "12345"
    # enriched cross-catalog ids merged in
    assert match.external_ids.musicbrainz_recording == "abc-123-mbid"
    assert match.external_ids.discogs_release == 999
    assert match.resolved is not None


def test_identify_audio_no_match(fake_xazam):
    class _NoMatchClient(_FakeClient):
        async def identify(self, audio_bytes):
            return _FakeResult(matched=False)

    fake_xazam.ShazamClient = _NoMatchClient
    match = identify_audio(b"fake-audio-bytes")
    assert match.matched is False
    assert match.title == ""


def test_identify_audio_missing_xazam_raises_clear_error(no_xazam):
    with pytest.raises(AudioIdentifyError) as exc:
        identify_audio(b"fake-audio-bytes")
    assert "xazam" in str(exc.value)
    assert "metadatarr[identify]" in str(exc.value)


def test_identify_audio_accepts_file_path(tmp_path, fake_xazam):
    audio_file = tmp_path / "song.mp3"
    audio_file.write_bytes(b"not-real-audio")

    with mock.patch("metadatarr.identify.run_resolve", return_value=_fake_resolve_result()), \
         mock.patch("metadatarr.identify.run_enrich", return_value=ExternalIds()):
        match = identify_audio(str(audio_file))

    assert match.matched is True
    assert match.title == "Never Gonna Give You Up"


# ---------------------------------------------------------------------------
# Server endpoint
# ---------------------------------------------------------------------------

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from metadatarr.server.app import create_app  # noqa: E402


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


def test_identify_audio_endpoint_success(client, fake_xazam):
    with mock.patch("metadatarr.identify.run_resolve", return_value=_fake_resolve_result()), \
         mock.patch("metadatarr.identify.run_enrich", return_value=ExternalIds()):
        resp = client.post(
            "/identify/audio",
            files={"file": ("song.mp3", io.BytesIO(b"fake-bytes"), "audio/mpeg")},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    assert body["title"] == "Never Gonna Give You Up"
    assert body["artist"] == "Rick Astley"
    assert body["isrc"] == "GBARL8600001"
    assert body["external_ids"]["musicbrainz_recording"] == "abc-123-mbid"


def test_identify_audio_endpoint_missing_xazam_returns_503(client, no_xazam):
    resp = client.post(
        "/identify/audio",
        files={"file": ("song.mp3", io.BytesIO(b"fake-bytes"), "audio/mpeg")},
    )
    assert resp.status_code == 503
    assert "xazam" in resp.json()["detail"]


def test_identify_audio_endpoint_requires_file_or_path(client):
    resp = client.post("/identify/audio")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

from metadatarr.cli import build_parser, cmd_identify  # noqa: E402


def test_cli_identify_wired(tmp_path, capsys):
    audio_file = tmp_path / "song.mp3"
    audio_file.write_bytes(b"not-real-audio")

    fake_match = mock.Mock(
        matched=True, title="Title", artist="Artist", album="Album",
        isrc="ISRC123", cover_art="",
    )
    fake_match.external_ids.model_dump.return_value = {}
    fake_match.external_ids.extra = {}

    with mock.patch("metadatarr.identify.identify_audio", return_value=fake_match):
        args = build_parser().parse_args(["identify", str(audio_file)])
        rc = args.func(args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "Title" in out
    assert "Artist" in out


def test_cli_identify_missing_xazam_nonzero_exit(tmp_path, capsys):
    audio_file = tmp_path / "song.mp3"
    audio_file.write_bytes(b"not-real-audio")

    with mock.patch("metadatarr.identify.identify_audio",
                    side_effect=AudioIdentifyError("xazam not installed; pip install metadatarr[identify]")):
        args = build_parser().parse_args(["identify", str(audio_file)])
        rc = args.func(args)

    assert rc == 1
    err = capsys.readouterr().err
    assert "xazam" in err
