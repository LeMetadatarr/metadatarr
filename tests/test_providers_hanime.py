"""Tests for the hanime provider (offline — pyhanime network is patched)."""
from __future__ import annotations

from unittest.mock import patch

from mediavocab import MediaType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from mediavocab.taxonomy.genre import GENRE_ADULT, GENRE_ANIME

from metadatarr.resolve.entities import EntityRole
from metadatarr.resolve.providers.hanime import HanimeProvider

from pyhanime.models import Franchise, Video, VideoPreview


def _preview(id=3214, name="Ruins Seeker 2", slug="ruins-seeker-2"):
    return VideoPreview(
        id=id, name=name, slug=slug, brand="Magin Label", brand_id="54",
        poster_url="", cover_url="", views=0, interests=0, likes=0,
        dislikes=0, downloads=0, monthly_rank=0, is_censored=True,
        created_at="", released_at="", created_at_unix=0, released_at_unix=0,
    )


def _video():
    return Video(
        id=3196, name="Ruins Seeker 1", slug="ruins-seeker-1",
        brand="Magin Label", brand_id="54", description_raw="",
        views=0, interests=0, likes=0, dislikes=0, downloads=0,
        monthly_rank=0, poster_url="", cover_url="", preview_url="",
        primary_color="", is_visible=True, is_censored=True,
        is_hard_subtitled=False, is_banned_in="", rating=0.0,
        duration_in_ms=858000, created_at="", released_at="",
        created_at_unix=0, released_at_unix=0,
        franchise=Franchise(id=1251, name="Ruins Seeker", slug="ruins-seeker"),
    )


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
    hits = [_preview(id=i, name=f"Ruins Seeker {i}", slug=f"rs-{i}") for i in range(10)]
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
