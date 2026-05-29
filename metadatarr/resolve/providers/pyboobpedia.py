"""Boobpedia performer-profile enrichment provider.

Boobpedia is a performer-focused wiki with structured physical stats,
measurements, and social links.  It carries no title data, so
:meth:`lookup` always returns ``None``.

The provider exposes two entry points:

1. :meth:`enrich` — called by the resolver pipeline on a work's
   :class:`ExternalIds`.  Re-fetches a known ``boobpedia_slug`` to fill
   missing attributes.

2. :func:`enrich_performer_entity` — module-level helper used by downstream
   scripts to hydrate a :class:`ProviderEntity` that already has a performer
   name or an existing ``boobpedia_slug``.

Keys written to a performer entity's :attr:`ExternalIds.extra`:

- ``boobpedia_slug``         — wiki page slug (stable canonical ID)
- ``boobpedia_url``          — canonical page URL
- ``boobpedia_birthday``     — raw date string
- ``boobpedia_birthplace``
- ``boobpedia_nationality``
- ``boobpedia_ethnicity``
- ``boobpedia_height_cm``    — int string
- ``boobpedia_weight_kg``    — int string
- ``boobpedia_measurements`` — "34DD-26-36"
- ``boobpedia_cup``
- ``boobpedia_bra_size``
- ``boobpedia_boobs_type``   — "Natural" | "Enhanced"
- ``boobpedia_waist_cm``
- ``boobpedia_hip_cm``
- ``boobpedia_hair_color``
- ``boobpedia_eye_color``
- ``boobpedia_body_type``
- ``boobpedia_aliases``      — JSON array
- ``boobpedia_categories``   — JSON array (top 20)
- ``boobpedia_photo_url``
- ``boobpedia_description``  — first 200 chars
- ``boobpedia_twitter``
- ``boobpedia_instagram``
- ``boobpedia_onlyfans``

Cross-source linking
--------------------
When a performer's boobpedia profile lists an IAFD link in social links,
the provider extracts the IAFD performer UUID and writes it as
``iafd_performer_uuid`` so the IAFD provider can enrich further.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import Optional

from mediavocab import MediaType, PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity

LOG = logging.getLogger("metadatarr.resolve.providers.pyboobpedia")


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _extract_iafd_uuid(iafd_url: str) -> Optional[str]:
    """Extract IAFD performer UUID from a URL like
    https://www.iafd.com/person.rme/id=UUID or
    https://www.iafd.com/person.rme/perfid=slug/gender=f/name.htm
    """
    if not iafd_url:
        return None
    m = re.search(r"/id=([^/&?]+)", iafd_url)
    if m:
        return m.group(1)
    return None


class BoobpediaProvider(MetadataProvider):
    """Boobpedia performer enrichment provider."""

    name = "boobpedia"
    media: set = set()
    playback_type: set = set()

    def is_available(self) -> bool:
        try:
            import pyboobpedia  # noqa: F401
            return True
        except ImportError:
            return False

    def lookup(self, signals: Signals) -> None:
        return None

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Re-fetch a known ``boobpedia_slug`` to fill missing attributes."""
        slug = external_ids.extra.get("boobpedia_slug")
        if not slug:
            return None
        if ("boobpedia_birthday" in external_ids.extra
                and "boobpedia_height_cm" in external_ids.extra):
            return None
        try:
            import pyboobpedia as _bp
            from pyboobpedia.ids import performer_to_extra
            p = _bp.get_performer(slug)
            return ExternalIds(extra=performer_to_extra(p))
        except Exception as exc:
            LOG.warning("boobpedia: enrich %r: %s", slug, exc)
            return None


def enrich_performer_entity(entity: ProviderEntity) -> ProviderEntity:
    """Resolve a performer against Boobpedia and merge data into the entity.

    Resolution order:

    1. If ``extra["boobpedia_slug"]`` is already set and ``boobpedia_birthday``
       is absent, re-fetch by slug to complete enrichment.
    2. If both ``boobpedia_slug`` and ``boobpedia_birthday`` are present, return
       unchanged (already enriched).
    3. Otherwise search by name; exact match first, then fuzzy ≥ 0.80.

    Cross-links: if the performer's boobpedia profile has an IAFD social link,
    the IAFD performer UUID is extracted and written as ``iafd_performer_uuid``.

    The entity is returned unchanged when:

    - ``pyboobpedia`` is not installed
    - no match is found
    - the network request fails
    """
    try:
        import pyboobpedia as _bp
        from pyboobpedia.ids import performer_to_extra
    except ImportError:
        return entity

    if not entity.name and not entity.external_ids.extra.get("boobpedia_slug"):
        return entity

    slug = entity.external_ids.extra.get("boobpedia_slug")

    # Already fully enriched
    if slug and "boobpedia_birthday" in entity.external_ids.extra:
        return entity

    # Slug present but not enriched — re-fetch
    if slug and "boobpedia_birthday" not in entity.external_ids.extra:
        try:
            performer = _bp.get_performer(slug)
            extra = performer_to_extra(performer)
            _maybe_cross_link(performer, extra)
            merged = entity.external_ids.merge(ExternalIds(extra=extra))
            return entity.model_copy(update={"external_ids": merged})
        except Exception as exc:
            LOG.warning("boobpedia: get_performer(%r): %s", slug, exc)
            return entity

    # Name-based search
    if not entity.name:
        return entity

    try:
        results = _bp.search_performers(entity.name)
    except Exception as exc:
        LOG.warning("boobpedia: search_performers(%r): %s", entity.name, exc)
        return entity

    if not results:
        return entity

    name_lower = entity.name.lower()
    match = next((r for r in results if r.name.lower() == name_lower), None)

    if match is None:
        scored = sorted(
            results,
            key=lambda r: _ratio(name_lower, r.name.lower()),
            reverse=True,
        )
        top_ratio = _ratio(name_lower, scored[0].name.lower())
        if scored and top_ratio >= 0.80:
            match = scored[0]

    if match is None:
        return entity

    try:
        performer = _bp.get_performer(match.slug)
    except Exception as exc:
        LOG.warning("boobpedia: get_performer(%r) for %r: %s", match.slug, match.name, exc)
        return entity

    extra = performer_to_extra(performer)
    _maybe_cross_link(performer, extra)
    merged = entity.external_ids.merge(ExternalIds(extra=extra))
    return entity.model_copy(update={"external_ids": merged})


def _maybe_cross_link(performer, extra: dict) -> None:
    """If performer has an IAFD social link, extract UUID for cross-linking."""
    iafd_url = performer.social.iafd if performer.social else ""
    if iafd_url:
        uuid = _extract_iafd_uuid(iafd_url)
        if uuid and "iafd_performer_uuid" not in extra:
            extra["iafd_performer_uuid"] = uuid


register(BoobpediaProvider())
