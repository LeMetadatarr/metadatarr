"""Tests for the pyfreeones provider and enrich_performer_entity helper."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from metadatarr.resolve.providers.pyfreeones import FreeonesProvider, enrich_performer_entity


# ---------------------------------------------------------------------------
# Minimal stubs mirroring pyfreeones dataclass shapes
# ---------------------------------------------------------------------------

@dataclass
class _Measurements:
    bust_raw: str = ""
    bust_cm: Optional[int] = None
    cup: str = ""
    bra: str = ""
    waist_raw: str = ""
    waist_cm: Optional[int] = None
    hip_raw: str = ""
    hip_cm: Optional[int] = None


@dataclass
class _PhysicalStats:
    height_raw: str = ""
    height_cm: Optional[int] = None
    weight_raw: str = ""
    weight_kg: Optional[int] = None
    measurements: _Measurements = field(default_factory=_Measurements)
    boobs: str = ""
    butt: str = ""
    hair_color: str = ""
    eye_color: str = ""
    ethnicity: str = ""
    nationality: str = ""
    shoe_size: str = ""
    tattoos: Optional[bool] = None
    tattoo_locations: str = ""
    piercings: Optional[bool] = None
    piercing_locations: str = ""


@dataclass
class _SocialLinks:
    twitter: str = ""
    instagram: str = ""
    facebook: str = ""
    tiktok: str = ""
    snapchat: str = ""
    onlyfans: str = ""
    manyvids: str = ""
    fancentro: str = ""
    modelhub: str = ""
    pornhub: str = ""
    other: List[str] = field(default_factory=list)


@dataclass
class _Performer:
    slug: str
    name: str
    url: str
    aliases: List[str] = field(default_factory=list)
    date_of_birth: str = ""
    birth_year: Optional[int] = None
    age: Optional[int] = None
    zodiac: str = ""
    place_of_birth: str = ""
    nationality: str = ""
    career_status: str = ""
    career_start: str = ""
    career_end: str = ""
    professions: List[str] = field(default_factory=list)
    is_feature_dancer: Optional[bool] = None
    stats: _PhysicalStats = field(default_factory=_PhysicalStats)
    photo_url: str = ""
    social: _SocialLinks = field(default_factory=_SocialLinks)


@dataclass
class _SearchResult:
    slug: str
    name: str
    url: str
    photo_url: str = ""


def _make_performer(
    slug: str = "abella-danger",
    name: str = "Abella Danger",
    nationality: str = "American",
    aliases: Optional[List[str]] = None,
    onlyfans: str = "",
    pornhub: str = "",
    photo_url: str = "https://thumbs.freeones.com/abella-danger.jpg",
) -> _Performer:
    social = _SocialLinks(onlyfans=onlyfans, pornhub=pornhub)
    return _Performer(
        slug=slug,
        name=name,
        url=f"https://www.freeones.com/{slug}/bio",
        aliases=aliases or [],
        nationality=nationality,
        photo_url=photo_url,
        social=social,
    )


def _make_search_result(slug: str = "abella-danger", name: str = "Abella Danger") -> _SearchResult:
    return _SearchResult(slug=slug, name=name, url=f"https://www.freeones.com/{slug}/bio")


def _entity(name: str = "Abella Danger") -> ProviderEntity:
    return ProviderEntity(role=EntityRole.ACTOR, name=name, external_ids=ExternalIds())


def _mock_pyfreeones(results=None, performer=None):
    mock = MagicMock()
    mock.search_performers.return_value = results if results is not None else [_make_search_result()]
    mock.get_performer.return_value = performer if performer is not None else _make_performer()
    return mock


# ---------------------------------------------------------------------------
# Provider basics
# ---------------------------------------------------------------------------

def test_lookup_always_returns_none():
    assert FreeonesProvider().lookup(Signals(title="Abella Danger")) is None


def test_enrich_always_returns_none():
    assert FreeonesProvider().enrich(ExternalIds()) is None


def test_media_set_is_empty():
    assert FreeonesProvider().media == set()


def test_is_available_true():
    pytest.importorskip("pyfreeones")
    assert FreeonesProvider().is_available() is True


def test_is_available_false_on_import_error():
    with patch.dict("sys.modules", {"pyfreeones": None}):
        assert FreeonesProvider().is_available() is False


# ---------------------------------------------------------------------------
# enrich_performer_entity — happy path
# ---------------------------------------------------------------------------

def test_enrich_adds_freeones_url():
    performer = _make_performer(slug="abella-danger")
    mock_pf = _mock_pyfreeones(performer=performer)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        result = enrich_performer_entity(_entity("Abella Danger"))

    assert result.external_ids.extra["freeones_url"] == "https://www.freeones.com/abella-danger/bio"


def test_enrich_adds_photo_url():
    performer = _make_performer(photo_url="https://thumbs.freeones.com/abella.jpg")
    mock_pf = _mock_pyfreeones(performer=performer)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        result = enrich_performer_entity(_entity("Abella Danger"))

    assert result.external_ids.extra["freeones_photo_url"] == "https://thumbs.freeones.com/abella.jpg"


def test_enrich_adds_nationality():
    performer = _make_performer(nationality="Brazilian")
    mock_pf = _mock_pyfreeones(performer=performer)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        result = enrich_performer_entity(_entity("Abella Danger"))

    assert result.external_ids.extra["freeones_nationality"] == "Brazilian"


def test_enrich_adds_aliases_as_json():
    performer = _make_performer(aliases=["Abby D", "AD"])
    mock_pf = _mock_pyfreeones(performer=performer)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        result = enrich_performer_entity(_entity("Abella Danger"))

    parsed = json.loads(result.external_ids.extra["freeones_aliases"])
    assert "Abby D" in parsed
    assert "AD" in parsed


def test_enrich_adds_onlyfans():
    performer = _make_performer(onlyfans="https://onlyfans.com/abella-danger")
    mock_pf = _mock_pyfreeones(performer=performer)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        result = enrich_performer_entity(_entity("Abella Danger"))

    assert result.external_ids.extra["freeones_onlyfans"] == "https://onlyfans.com/abella-danger"


def test_enrich_no_onlyfans_key_when_empty():
    performer = _make_performer(onlyfans="")
    mock_pf = _mock_pyfreeones(performer=performer)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        result = enrich_performer_entity(_entity("Abella Danger"))

    assert "freeones_onlyfans" not in result.external_ids.extra


# ---------------------------------------------------------------------------
# Cross-link to Pornhub slug
# ---------------------------------------------------------------------------

def test_enrich_extracts_pornhub_slug_from_model_url():
    performer = _make_performer(pornhub="https://www.pornhub.com/model/abella-danger")
    mock_pf = _mock_pyfreeones(performer=performer)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        result = enrich_performer_entity(_entity("Abella Danger"))

    assert result.external_ids.extra["pornhub_slug"] == "abella-danger"


def test_enrich_extracts_pornhub_slug_from_pornstar_url():
    results = [_make_search_result("riley-reid", "Riley Reid")]
    performer = _make_performer(slug="riley-reid", name="Riley Reid",
                                pornhub="https://www.pornhub.com/pornstar/riley-reid")
    mock_pf = _mock_pyfreeones(results=results, performer=performer)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        result = enrich_performer_entity(_entity("Riley Reid"))

    assert result.external_ids.extra["pornhub_slug"] == "riley-reid"


def test_enrich_no_pornhub_key_when_no_link():
    performer = _make_performer(pornhub="")
    mock_pf = _mock_pyfreeones(performer=performer)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        result = enrich_performer_entity(_entity("Abella Danger"))

    assert "pornhub_slug" not in result.external_ids.extra


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

def test_enrich_prefers_exact_name_match():
    results = [
        _make_search_result("abella-danger-xx", "Abella Danger XX"),
        _make_search_result("abella-danger", "Abella Danger"),
    ]
    performer = _make_performer(slug="abella-danger", name="Abella Danger")
    mock_pf = _mock_pyfreeones(results=results, performer=performer)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        enrich_performer_entity(_entity("Abella Danger"))

    mock_pf.get_performer.assert_called_once_with("abella-danger")


def test_enrich_fuzzy_match_fallback():
    results = [_make_search_result("riley-reid", "Riley Reid")]
    performer = _make_performer(slug="riley-reid", name="Riley Reid")
    mock_pf = _mock_pyfreeones(results=results, performer=performer)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        result = enrich_performer_entity(_entity("Riley  Reid"))  # extra space

    assert result.external_ids.extra.get("freeones_url") is not None


def test_enrich_returns_entity_unchanged_when_no_results():
    mock_pf = _mock_pyfreeones(results=[])

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        entity = _entity("Unknown Performer")
        result = enrich_performer_entity(entity)

    assert result.external_ids.extra == {}


def test_enrich_returns_entity_unchanged_on_poor_fuzzy_match():
    results = [_make_search_result("totally-different", "Totally Different")]
    mock_pf = _mock_pyfreeones(results=results)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        entity = _entity("Abella Danger")
        result = enrich_performer_entity(entity)

    assert result.external_ids.extra == {}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_enrich_returns_entity_unchanged_when_library_missing():
    with patch.dict("sys.modules", {"pyfreeones": None}):
        entity = _entity("Abella Danger")
        result = enrich_performer_entity(entity)
    assert result is entity


def test_enrich_returns_entity_unchanged_on_search_error():
    mock_pf = MagicMock()
    mock_pf.search_performers.side_effect = RuntimeError("network error")

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        entity = _entity("Abella Danger")
        result = enrich_performer_entity(entity)

    assert result is entity


def test_enrich_returns_entity_unchanged_on_get_performer_error():
    mock_pf = _mock_pyfreeones()
    mock_pf.get_performer.side_effect = RuntimeError("404")

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        entity = _entity("Abella Danger")
        result = enrich_performer_entity(entity)

    assert result is entity


def test_enrich_returns_entity_unchanged_for_empty_name():
    entity = ProviderEntity(role=EntityRole.ACTOR, name="", external_ids=ExternalIds())
    result = enrich_performer_entity(entity)
    assert result is entity


# ---------------------------------------------------------------------------
# Existing external_ids are preserved after merge
# ---------------------------------------------------------------------------

def test_enrich_preserves_existing_external_ids():
    performer = _make_performer(nationality="American")
    mock_pf = _mock_pyfreeones(performer=performer)

    existing = ExternalIds(extra={"iafd_id": "some-uuid"})
    entity = ProviderEntity(role=EntityRole.ACTOR, name="Abella Danger", external_ids=existing)

    with patch.dict("sys.modules", {"pyfreeones": mock_pf}):
        result = enrich_performer_entity(entity)

    assert result.external_ids.extra["iafd_id"] == "some-uuid"
    assert "freeones_url" in result.external_ids.extra
