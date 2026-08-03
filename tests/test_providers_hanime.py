"""Tests for the hanime provider (offline).

pyhanime is not installable from PyPI, so these tests run against an in-file
stand-in registered in ``sys.modules``: lightweight work objects plus adapter
functions implementing pyhanime's documented identifier contract
(``hanime_video_id`` / ``hanime_brand_id`` / ``hanime_franchise_id`` /
``hanime_slug`` / ``hanime_url``). The provider imports pyhanime lazily, so
the stand-in is what it sees in every environment and the tests behave the
same whether or not the real package is installed.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Optional
from unittest.mock import patch

import pytest

from mediavocab import MediaType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from mediavocab.taxonomy.genre import GENRE_ADULT, GENRE_ANIME

from metadatarr.resolve.entities import EntityRole
from metadatarr.resolve.providers.hanime import HanimeProvider


# --- pyhanime stand-in -----------------------------------------------------

@dataclass
class _Franchise:
    id: int = 1251
    name: str = "Ruins Seeker"
    slug: str = "ruins-seeker"


@dataclass
class _Work:
    """Shape shared by pyhanime's Video and VideoPreview objects."""
    id: int = 3214
    name: str = "Ruins Seeker 2"
    slug: str = "ruins-seeker-2"
    brand: str = "Magin Label"
    brand_id: str = "54"
    duration_in_ms: int = 0
    franchise: Optional[_Franchise] = None

    @property
    def url(self) -> str:
        return f"https://hanime.tv/videos/hentai/{self.slug}"


def _stub_external_ids(obj) -> dict:
    """pyhanime.mediavocab.external_ids identifier contract."""
    extra = {}
    if getattr(obj, "id", 0):
        extra["hanime_video_id"] = str(obj.id)
    if getattr(obj, "brand_id", ""):
        extra["hanime_brand_id"] = str(obj.brand_id)
    franchise = getattr(obj, "franchise", None)
    if franchise is not None and getattr(franchise, "id", 0):
        extra["hanime_franchise_id"] = str(franchise.id)
    if getattr(obj, "slug", ""):
        extra["hanime_slug"] = obj.slug
        extra["hanime_url"] = obj.url
    return extra


def _stub_studio_external_ids(obj) -> dict:
    """pyhanime.mediavocab.studio_external_ids identifier contract."""
    extra = {}
    if getattr(obj, "brand_id", ""):
        extra["hanime_brand_id"] = str(obj.brand_id)
    return extra


def _make_stub_pyhanime() -> dict:
    root = types.ModuleType("pyhanime")
    root.search = lambda query: []
    root.get_video = lambda slug: None
    mv = types.ModuleType("pyhanime.mediavocab")
    mv.external_ids = _stub_external_ids
    mv.studio_external_ids = _stub_studio_external_ids
    root.mediavocab = mv
    return {"pyhanime": root, "pyhanime.mediavocab": mv}


@pytest.fixture(autouse=True)
def _pyhanime_stub():
    with patch.dict(sys.modules, _make_stub_pyhanime()):
        yield


def _preview(id=3214, name="Ruins Seeker 2", slug="ruins-seeker-2"):
    return _Work(id=id, name=name, slug=slug)


def _video():
    return _Work(id=3196, name="Ruins Seeker 1", slug="ruins-seeker-1",
                 duration_in_ms=858000, franchise=_Franchise())


# --- routing / gating ---

def test_gated_off_for_mainstream_movie():
    p = HanimeProvider()
    assert p.matches(Signals(title="Inception", medium=MediaType.MOVIE)) is False


def test_gated_on_for_adult_anime():
    p = HanimeProvider()
    s = Signals(title="Bible Black", medium=MediaType.MOVIE,
                content_genres=[GENRE_ADULT, GENRE_ANIME])
    assert p.matches(s) is True


def test_refuses_unsupported_medium():
    p = HanimeProvider()
    with patch("pyhanime.search") as search:
        assert p.lookup(Signals(title="x", medium=MediaType.MUSIC)) is None
        search.assert_not_called()


# --- lookup ---

def test_lookup_picks_best_title_and_builds_ids():
    p = HanimeProvider()
    hits = [_preview(name="Unrelated", slug="unrelated"),
            _preview(name="Ruins Seeker 1", slug="ruins-seeker-1", id=3196)]
    with patch("pyhanime.search", return_value=hits):
        m = p.lookup(Signals(title="Ruins Seeker 1"))
    assert m is not None
    assert m.provider == "hanime"
    assert m.external_ids.extra["hanime_video_id"] == "3196"
    assert m.external_ids.extra["hanime_brand_id"] == "54"
    assert m.confidence <= 0.75


def test_lookup_emits_studio_relation():
    p = HanimeProvider()
    with patch("pyhanime.search", return_value=[_preview()]):
        m = p.lookup(Signals(title="Ruins Seeker 2"))
    studios = m.relations[EntityRole.STUDIO]
    assert studios[0].name == "Magin Label"
    assert studios[0].external_ids.extra["hanime_brand_id"] == "54"


def test_lookup_candidates_ranked_and_capped():
    p = HanimeProvider()
    hits = [_preview(id=i + 1, name=f"Ruins Seeker {i}", slug=f"rs-{i}")
            for i in range(10)]
    with patch("pyhanime.search", return_value=hits):
        cands = p.lookup_candidates(Signals(title="Ruins Seeker 1"))
    assert 0 < len(cands) <= 5


def test_lookup_none_on_empty():
    p = HanimeProvider()
    with patch("pyhanime.search", return_value=[]):
        assert p.lookup(Signals(title="nothing")) is None


# --- enrich ---

def test_enrich_by_slug_adds_franchise():
    p = HanimeProvider()
    with patch("pyhanime.get_video", return_value=_video()) as gv:
        out = p.enrich(ExternalIds(extra={"hanime_slug": "ruins-seeker-1"}))
    gv.assert_called_once_with("ruins-seeker-1")
    assert out.extra["hanime_franchise_id"] == "1251"


def test_enrich_without_slug_returns_none():
    assert HanimeProvider().enrich(ExternalIds()) is None


# --- availability ---

def test_available_with_package_importable():
    assert HanimeProvider().is_available() is True
