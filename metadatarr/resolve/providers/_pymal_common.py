"""Shared helpers for the pymal-backed providers (MyAnimeList scraper).

Not a provider module itself (underscore prefix excludes it from the
auto-discovery loop in ``providers/__init__.py``). Holds the ARM
cross-reference bridge and the card/detail-to-``ProviderMatch``/relation
conversion logic shared by ``pymal_anime.py``, ``pymal_manga.py``,
``pymal_person.py`` and ``pymal_character.py``.
"""
from __future__ import annotations

import logging
from typing import Optional

from mediavocab import MediaType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from mediavocab.taxonomy import GENRE_ANIME, GENRE_MANGA
from metadatarr.resolve.base import ProviderMatch
from metadatarr.resolve.entities import EntityRole, ProviderEntity

LOG = logging.getLogger("metadatarr.resolve.providers.pymal")

_AVAILABLE: Optional[bool] = None


def _check_available() -> bool:
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            import pymal as _  # noqa: F401
            _AVAILABLE = True
        except ImportError:
            _AVAILABLE = False
    return _AVAILABLE


# ---------------------------------------------------------------------------
# ARM helper
# ---------------------------------------------------------------------------

def _arm_enrich(mal_id: int) -> ExternalIds:
    try:
        from pymal.arm import get_ids, to_external_ids
        return to_external_ids(get_ids(mal_id))
    except Exception as exc:
        LOG.warning("ARM enrich failed for mal_id=%s: %s", mal_id, exc)
        return ExternalIds()


def _arm_enrich_any(external_ids: ExternalIds) -> ExternalIds:
    """ARM lookup using whichever anime ID is available (bidirectional)."""
    try:
        from pymal.arm import enrich_external_ids, to_external_ids
        data = enrich_external_ids(external_ids)
        return to_external_ids(data) if data else ExternalIds()
    except Exception as exc:
        LOG.warning("ARM bidirectional enrich failed: %s", exc)
        return ExternalIds()


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def _anime_card_to_match(card, provider: str = "pymal_anime") -> ProviderMatch:
    arm_ids = _arm_enrich(card.mal_id)
    return ProviderMatch(
        provider=provider,
        confidence=0.80,
        signals=Signals(
            title=card.title,
            medium=MediaType.EPISODIC_SERIES,
            content_genres=[GENRE_ANIME],
        ),
        external_ids=ExternalIds(mal_id=card.mal_id).merge(arm_ids),
    )


def _manga_card_to_match(card, provider: str = "pymal_manga") -> ProviderMatch:
    arm_ids = _arm_enrich(card.mal_id)
    return ProviderMatch(
        provider=provider,
        confidence=0.80,
        signals=Signals(
            title=card.title,
            medium=MediaType.COMIC,
            content_genres=[GENRE_MANGA],
        ),
        external_ids=ExternalIds(mal_id=card.mal_id).merge(arm_ids),
    )


def _relations_from_anime(anime) -> dict:
    relations: dict = {}

    for studio_name in anime.studios:
        studio_mal_id = anime.studio_ids.get(studio_name)
        s_ids = ExternalIds(mal_studio_id=studio_mal_id) if studio_mal_id else ExternalIds()
        relations.setdefault(EntityRole.STUDIO, []).append(ProviderEntity(
            role=EntityRole.STUDIO,
            name=studio_name,
            external_ids=s_ids,
        ))

    for producer_name in anime.producers:
        prod_mal_id = anime.producer_ids.get(producer_name)
        p_ids = ExternalIds(mal_studio_id=prod_mal_id) if prod_mal_id else ExternalIds()
        relations.setdefault(EntityRole.PRODUCER, []).append(ProviderEntity(
            role=EntityRole.PRODUCER,
            name=producer_name,
            external_ids=p_ids,
        ))

    for char in anime.characters:
        char_ids = ExternalIds(mal_character_id=char.mal_id if char.mal_id else None)
        relations.setdefault(EntityRole.OTHER, []).append(ProviderEntity(
            role=EntityRole.OTHER,
            name=char.name,
            external_ids=char_ids,
        ))
        if char.voice_actor_name:
            va_ids = ExternalIds()
            if char.va_url:
                import re as _re
                m = _re.search(r"/people/(\d+)/", char.va_url)
                if m:
                    va_ids = ExternalIds(mal_person_id=int(m.group(1)))
            relations.setdefault(EntityRole.VOICE_ACTOR, []).append(ProviderEntity(
                role=EntityRole.VOICE_ACTOR,
                name=char.voice_actor_name,
                external_ids=va_ids,
            ))

    for staff in anime.staff:
        role_str = (staff.role or "").lower()
        if "director" in role_str:
            er = EntityRole.DIRECTOR
        elif "producer" in role_str:
            er = EntityRole.PRODUCER
        elif "composer" in role_str or "music" in role_str:
            er = EntityRole.COMPOSER
        elif "script" in role_str or "series composition" in role_str or "screenplay" in role_str:
            er = EntityRole.WRITER
        else:
            er = EntityRole.OTHER
        staff_ids = ExternalIds(mal_person_id=staff.mal_id if staff.mal_id else None)
        relations.setdefault(er, []).append(ProviderEntity(
            role=er,
            name=staff.name,
            external_ids=staff_ids,
        ))

    return relations


def _relations_from_manga(manga) -> dict:
    relations: dict = {}
    for author in manga.authors:
        author_ids = ExternalIds(mal_person_id=author.mal_id if author.mal_id else None)
        relations.setdefault(EntityRole.AUTHOR, []).append(ProviderEntity(
            role=EntityRole.AUTHOR,
            name=author.name,
            external_ids=author_ids,
        ))
    return relations
