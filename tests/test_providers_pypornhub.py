"""Tests for the pypornhub provider."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

from mediavocab import MediaType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.entities import EntityRole
from metadatarr.resolve.providers.pypornhub import PornhubProvider, get_model_profile


# ---------------------------------------------------------------------------
# Minimal stubs — mirrors pypornhub's actual dataclass shapes
# ---------------------------------------------------------------------------

@dataclass
class _PornstarRef:
    slug: str
    name: str

    @property
    def url(self) -> str:
        return f"https://www.pornhub.com/pornstar/{self.slug}"


@dataclass
class _MediaStream:
    quality: str
    format: str
    url: str
    height: Optional[int] = None
    is_default: bool = False


@dataclass
class _VideoItem:
    video_id: str
    vkey: str
    title: str
    url: str
    thumbnail: str = ""
    duration: str = ""


@dataclass
class _VideoMeta:
    video_id: int
    vkey: str
    title: str
    url: str
    thumbnail: str = ""
    duration_seconds: int = 0
    tags: List[str] = field(default_factory=list)
    pornstars: List[_PornstarRef] = field(default_factory=list)
    streams: List[_MediaStream] = field(default_factory=list)

    @property
    def best_stream(self) -> Optional[_MediaStream]:
        hls = [s for s in self.streams if s.format == "hls" and s.height]
        if hls:
            return max(hls, key=lambda s: s.height or 0)
        return self.streams[0] if self.streams else None


def _make_video_item(title: str = "Test Scene", vkey: str = "abc123") -> _VideoItem:
    return _VideoItem(
        video_id="99",
        vkey=vkey,
        title=title,
        url=f"https://www.pornhub.com/view_video.php?viewkey={vkey}",
    )


def _make_video_meta(
    title: str = "Test Scene",
    vkey: str = "abc123",
    tags: Optional[List[str]] = None,
    pornstars: Optional[List[_PornstarRef]] = None,
    stream_url: str = "https://cdn.phncdn.com/test.m3u8",
) -> _VideoMeta:
    return _VideoMeta(
        video_id=99,
        vkey=vkey,
        title=title,
        url=f"https://www.pornhub.com/view_video.php?viewkey={vkey}",
        duration_seconds=1234,
        tags=tags or ["milf", "hd"],
        pornstars=pornstars or [
            _PornstarRef(slug="abella-danger", name="Abella Danger"),
            _PornstarRef(slug="riley-reid", name="Riley Reid"),
        ],
        streams=[_MediaStream(quality="1080", format="hls", url=stream_url, height=1080)],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _provider() -> PornhubProvider:
    p = PornhubProvider.__new__(PornhubProvider)
    return p


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

def test_is_available_true():
    pytest.importorskip("pypornhub")
    assert PornhubProvider().is_available() is True


def test_is_available_false_when_import_fails():
    with patch.dict("sys.modules", {"pypornhub": None}):
        assert _provider().is_available() is False


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------

def test_lookup_returns_none_for_wrong_media_type():
    provider = _provider()
    result = provider.lookup(Signals(title="Test", medium=MediaType.MUSIC))
    assert result is None


def test_lookup_returns_none_for_empty_title():
    provider = _provider()
    assert provider.lookup(Signals()) is None


def test_lookup_success():
    item = _make_video_item("Exact Scene Title", vkey="xyz789")
    meta = _make_video_meta("Exact Scene Title", vkey="xyz789")

    mock_ph = MagicMock()
    mock_ph.search_videos.return_value = [item]
    mock_ph.fetch_video.return_value = meta

    with patch.dict("sys.modules", {"pypornhub": mock_ph}):
        provider = _provider()
        result = provider.lookup(Signals(title="Exact Scene Title", medium=MediaType.SHORT_FILM))

    assert result is not None
    assert result.provider == "pornhub"
    assert result.external_ids.extra["pornhub_vkey"] == "xyz789"
    assert result.external_ids.extra["pornhub_url"] != ""
    assert result.confidence > 0


def test_lookup_skips_poor_title_match():
    item = _make_video_item("Completely Different Video", vkey="zzz")
    mock_ph = MagicMock()
    mock_ph.search_videos.return_value = [item]

    with patch.dict("sys.modules", {"pypornhub": mock_ph}):
        result = _provider().lookup(Signals(title="Specific Niche Scene"))

    assert result is None


def test_lookup_returns_none_on_search_error():
    mock_ph = MagicMock()
    mock_ph.search_videos.side_effect = RuntimeError("network error")

    with patch.dict("sys.modules", {"pypornhub": mock_ph}):
        result = _provider().lookup(Signals(title="Test"))

    assert result is None


# ---------------------------------------------------------------------------
# Actor relations
# ---------------------------------------------------------------------------

def test_lookup_emits_actor_relations():
    item = _make_video_item("Scene With Cast", vkey="cast1")
    meta = _make_video_meta(
        "Scene With Cast",
        vkey="cast1",
        pornstars=[
            _PornstarRef(slug="abella-danger", name="Abella Danger"),
            _PornstarRef(slug="riley-reid", name="Riley Reid"),
        ],
    )
    mock_ph = MagicMock()
    mock_ph.search_videos.return_value = [item]
    mock_ph.fetch_video.return_value = meta

    with patch.dict("sys.modules", {"pypornhub": mock_ph}):
        result = _provider().lookup(Signals(title="Scene With Cast"))

    assert result is not None
    actors = result.relations.get(EntityRole.ACTOR, [])
    assert len(actors) == 2
    names = {e.name for e in actors}
    assert "Abella Danger" in names
    assert "Riley Reid" in names


def test_actor_entities_carry_pornhub_slug():
    item = _make_video_item("Slug Test", vkey="slug1")
    meta = _make_video_meta(
        "Slug Test",
        vkey="slug1",
        pornstars=[_PornstarRef(slug="abella-danger", name="Abella Danger")],
    )
    mock_ph = MagicMock()
    mock_ph.search_videos.return_value = [item]
    mock_ph.fetch_video.return_value = meta

    with patch.dict("sys.modules", {"pypornhub": mock_ph}):
        result = _provider().lookup(Signals(title="Slug Test"))

    actor = result.relations[EntityRole.ACTOR][0]
    assert actor.external_ids.extra.get("pornhub_slug") == "abella-danger"


# ---------------------------------------------------------------------------
# Tags go to extra, not relations
# ---------------------------------------------------------------------------

def test_tags_stored_in_extra_not_relations():
    item = _make_video_item("Tag Test", vkey="tag1")
    meta = _make_video_meta("Tag Test", vkey="tag1", tags=["milf", "hd", "amateur"])
    mock_ph = MagicMock()
    mock_ph.search_videos.return_value = [item]
    mock_ph.fetch_video.return_value = meta

    with patch.dict("sys.modules", {"pypornhub": mock_ph}):
        result = _provider().lookup(Signals(title="Tag Test"))

    assert result is not None
    parsed = json.loads(result.external_ids.extra["tags"])
    assert "milf" in parsed
    # No ProviderEntity should be emitted for tags
    for entities in result.relations.values():
        for e in entities:
            assert e.name not in ("milf", "hd", "amateur")


# ---------------------------------------------------------------------------
# Stream URL
# ---------------------------------------------------------------------------

def test_best_stream_url_in_extra():
    item = _make_video_item("Stream Test", vkey="strm1")
    meta = _make_video_meta("Stream Test", vkey="strm1", stream_url="https://cdn.phncdn.com/test.m3u8")
    mock_ph = MagicMock()
    mock_ph.search_videos.return_value = [item]
    mock_ph.fetch_video.return_value = meta

    with patch.dict("sys.modules", {"pypornhub": mock_ph}):
        result = _provider().lookup(Signals(title="Stream Test"))

    assert result.external_ids.extra.get("pornhub_stream_url") == "https://cdn.phncdn.com/test.m3u8"


# ---------------------------------------------------------------------------
# enrich
# ---------------------------------------------------------------------------

def test_enrich_by_vkey():
    meta = _make_video_meta("Enriched Scene", vkey="enr1")
    mock_ph = MagicMock()
    mock_ph.fetch_video.return_value = meta

    ext = ExternalIds(extra={"pornhub_vkey": "enr1"})
    with patch.dict("sys.modules", {"pypornhub": mock_ph}):
        out = _provider().enrich(ext)

    assert out is not None
    assert out.extra["pornhub_vkey"] == "enr1"


def test_enrich_returns_none_without_vkey():
    ext = ExternalIds()
    assert _provider().enrich(ext) is None


def test_enrich_returns_none_on_error():
    mock_ph = MagicMock()
    mock_ph.fetch_video.side_effect = RuntimeError("gone")
    ext = ExternalIds(extra={"pornhub_vkey": "bad"})
    with patch.dict("sys.modules", {"pypornhub": mock_ph}):
        assert _provider().enrich(ext) is None


# ---------------------------------------------------------------------------
# get_model_profile helper
# ---------------------------------------------------------------------------

def test_get_model_profile_returns_profile():
    mock_profile = MagicMock()
    mock_ph = MagicMock()
    mock_ph.fetch_model.return_value = mock_profile

    with patch.dict("sys.modules", {"pypornhub": mock_ph}):
        result = get_model_profile("abella-danger")

    assert result is mock_profile


def test_get_model_profile_returns_none_on_error():
    mock_ph = MagicMock()
    mock_ph.fetch_model.side_effect = RuntimeError("404")

    with patch.dict("sys.modules", {"pypornhub": mock_ph}):
        assert get_model_profile("no-such-slug") is None
