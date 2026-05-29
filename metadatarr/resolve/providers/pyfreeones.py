"""FreeOnes performer-profile enrichment provider.

FreeOnes indexes performer profiles — biographical data, physical stats,
career info, and social-media links.  It is **not** a title database, so
:meth:`lookup` always returns ``None``.

The provider exposes two entry points:

1. :meth:`enrich` — called by the resolver pipeline on a work's
   :class:`ExternalIds`.  Irrelevant here; returns ``None``.

2. :func:`enrich_performer_entity` — module-level helper used by downstream
   scripts to hydrate a :class:`ProviderEntity` that already has a performer
   name (typically sourced from an IAFD or Pornhub match).

Keys written to a performer entity's :attr:`ExternalIds.extra`:

- ``freeones_url``        — canonical ``/slug/bio`` page URL
- ``freeones_photo_url``  — 350×350 profile thumbnail URL
- ``freeones_aliases``    — JSON array of known aliases
- ``freeones_onlyfans``   — OnlyFans profile URL if present
- ``freeones_nationality``— nationality string
"""
from __future__ import annotations

import difflib
import json
import logging
from typing import Optional

from mediavocab import MediaType, PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import ProviderEntity

LOG = logging.getLogger("metadatarr.resolve.providers.pyfreeones")


def _slug_to_external_ids(performer) -> ExternalIds:
    extra: dict = {
        "freeones_url": performer.url,
    }
    if performer.photo_url:
        extra["freeones_photo_url"] = performer.photo_url
    if performer.aliases:
        extra["freeones_aliases"] = json.dumps(performer.aliases)
    if performer.social.onlyfans:
        extra["freeones_onlyfans"] = performer.social.onlyfans
    if performer.nationality:
        extra["freeones_nationality"] = performer.nationality
    # Cross-link to Pornhub slug if the performer lists their PH model page
    ext = ExternalIds(extra=extra)
    if performer.social.pornhub:
        # Extract the slug from a URL like https://www.pornhub.com/model/abella-danger
        ph_url = performer.social.pornhub
        slug_part = ph_url.rstrip("/").split("/")[-1]
        if slug_part:
            ext.extra["pornhub_slug"] = slug_part
    return ext


class FreeonesProvider(MetadataProvider):
    name = "freeones"
    media: set = set()
    playback_type: set = set()

    def is_available(self) -> bool:
        try:
            import pyfreeones  # noqa: F401
            return True
        except ImportError:
            return False

    def lookup(self, signals: Signals) -> None:
        return None

    def enrich(self, external_ids: ExternalIds) -> None:
        return None


def enrich_performer_entity(entity: ProviderEntity) -> ProviderEntity:
    """Look up a performer on FreeOnes by name and merge profile data into
    the entity's :attr:`~ProviderEntity.external_ids`.

    The entity is returned unchanged if:

    - ``pyfreeones`` is not installed
    - no results are found for the entity's name
    - the search raises an exception

    The best match is chosen by case-insensitive exact name match first,
    then by :func:`difflib.SequenceMatcher` ratio against the full name and
    all aliases.
    """
    try:
        from pyfreeones import search_performers, get_performer
    except ImportError:
        return entity

    if not entity.name:
        return entity

    try:
        results = search_performers(entity.name)
    except Exception as exc:
        LOG.warning("freeones search failed for %r: %s", entity.name, exc)
        return entity

    if not results:
        return entity

    name_lower = entity.name.lower()

    # Exact match first
    match = next((r for r in results if r.name.lower() == name_lower), None)

    # Fuzzy fallback — highest ratio above threshold
    if match is None:
        scored = sorted(
            results,
            key=lambda r: difflib.SequenceMatcher(None, name_lower, r.name.lower()).ratio(),
            reverse=True,
        )
        if scored and difflib.SequenceMatcher(None, name_lower, scored[0].name.lower()).ratio() >= 0.8:
            match = scored[0]

    if match is None:
        return entity

    try:
        performer = get_performer(match.slug)
    except Exception as exc:
        LOG.warning("freeones get_performer failed for %r: %s", match.slug, exc)
        return entity

    profile_ids = _slug_to_external_ids(performer)
    merged = entity.external_ids.merge(profile_ids)
    return entity.model_copy(update={"external_ids": merged})


register(FreeonesProvider())
