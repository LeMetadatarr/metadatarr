"""IAFD (Internet Adult Film Database) metadata provider.

IAFD is the industry-standard adult film database.  It carries structured
data for ~862k titles and ~230k performers, with stable UUIDs for both.

Title lookup
------------
:meth:`IAFDProvider.lookup` searches IAFD by title string and returns a
:class:`ProviderMatch` with:

- Confidence up to **0.90** (IAFD is authoritative; boosted when year matches).
- Signals: title, year, runtime.
- ACTOR relations — one :class:`ProviderEntity` per cast member, each
  carrying ``extra["iafd_performer_uuid"]`` for later enrichment.
- A STUDIO relation for the distributor/studio when present.
- ``external_ids.extra["iafd_title_uuid"]`` — stable UUID for the title.

Performer enrichment
--------------------
:func:`enrich_performer_entity` resolves a performer by name (or existing
``iafd_performer_uuid``) and writes full biographical data into
``external_ids.extra``.  See :mod:`pyiafd.ids` for the complete key
reference.

Typically called after the title lookup populates ACTOR entities with names,
so downstream scripts can hydrate physical stats, social links, and aliases
without additional searches.

Title enrichment
----------------
:meth:`IAFDProvider.enrich` re-fetches a known ``iafd_title_uuid`` to fill
missing attributes (runtime, cover URL, full cast).

Cross-source linking
--------------------
When used alongside the ``freeones`` and ``lordofporn`` providers:

1. Title lookup writes ACTOR entities with ``iafd_performer_uuid`` set.
2. ``enrich_performer_entity`` from *this* module writes IAFD bio data.
3. ``enrich_performer_entity`` from ``pyfreeones`` / ``pylordofporn`` adds
   FreeOnes/TLoP slugs and photo URLs.
4. All keys land in the same :class:`EntityRecord` via ``ExternalIds.merge``,
   so ``iafd_performer_uuid`` and ``freeones_url`` always co-locate.

The ``iafd_performer_uuid`` is a stable UUID minted by IAFD — use it as
the primary cross-source anchor for adult performers.
"""
from __future__ import annotations

import difflib
import logging
from typing import Dict, List, Optional

from mediavocab import MediaType, PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity

LOG = logging.getLogger("metadatarr.resolve.providers.pyiafd")

_MEDIA = {MediaType.MOVIE, MediaType.SHORT_FILM}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _best_result(query: str, results, *, threshold: float = 0.65):
    """Return the best-matching result from a list, or None."""
    if not results:
        return None
    ql = query.lower()
    exact = next((r for r in results if r.name.lower() == ql), None)
    if exact:
        return exact
    scored = sorted(results, key=lambda r: _ratio(ql, r.name.lower()), reverse=True)
    if scored and _ratio(ql, scored[0].name.lower()) >= threshold:
        return scored[0]
    return None


def _actor_entities(cast) -> List[ProviderEntity]:
    """Build ACTOR ProviderEntities from a list of CastMember objects."""
    entities = []
    for member in cast:
        if not (member.name or "").strip():
            continue
        extra: dict = {}
        if member.id:
            extra["iafd_performer_uuid"] = member.id
        if getattr(member, "headshot_url", None):
            extra["iafd_photo_url"] = member.headshot_url
        entities.append(ProviderEntity(
            role=EntityRole.ACTOR,
            name=member.name.strip(),
            external_ids=ExternalIds(extra=extra),
        ))
    return entities


def _studio_entity(name: str) -> ProviderEntity:
    return ProviderEntity(
        role=EntityRole.STUDIO,
        name=name.strip(),
        external_ids=ExternalIds(),
    )


def _title_external_ids(title) -> ExternalIds:
    try:
        from pyiafd.ids import title_to_extra
        return ExternalIds(extra=title_to_extra(title))
    except ImportError:
        return ExternalIds(extra={"iafd_title_uuid": title.id})


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class IAFDProvider(MetadataProvider):
    """IAFD title lookup and title enrichment."""

    name = "iafd"
    media = _MEDIA
    playback_type = {PlaybackType.VIDEO}

    def is_available(self) -> bool:
        try:
            import pyiafd  # noqa: F401
            return True
        except ImportError:
            return False

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        """Search IAFD by title and return the best match."""
        if not signals.title:
            return None
        if signals.medium and signals.medium not in _MEDIA:
            return None

        import pyiafd as _iafd

        try:
            results = _iafd.search_titles(signals.title)
        except Exception as exc:
            LOG.warning("iafd: search_titles(%r) failed: %s", signals.title, exc)
            return None

        if not results:
            return None

        best = _best_result(signals.title, results, threshold=0.60)
        if best is None:
            return None

        ratio = _ratio(signals.title, best.name)

        # Prefer year-matching result when year is provided
        if signals.year and hasattr(best, "year"):
            year_hits = [
                r for r in results
                if getattr(r, "year", None) and str(r.year) == str(signals.year)
            ]
            if year_hits:
                year_best = _best_result(signals.title, year_hits, threshold=0.50)
                if year_best:
                    best = year_best
                    ratio = _ratio(signals.title, best.name)

        try:
            title = _iafd.get_title(best.id)
        except Exception as exc:
            LOG.warning("iafd: get_title(%r) failed: %s", best.id, exc)
            return None

        # Confidence: IAFD is authoritative — base 0.70, boosted by title
        # similarity and year match.
        confidence = 0.60 + 0.25 * ratio
        if signals.year and getattr(title, "year", None):
            if str(title.year) == str(signals.year):
                confidence = min(confidence + 0.10, 0.92)
        confidence = min(confidence, 0.90)

        runtime: Optional[float] = None
        if getattr(title, "runtime_minutes", None):
            runtime = float(title.runtime_minutes)

        external_ids = _title_external_ids(title)

        relations: Dict[EntityRole, List[ProviderEntity]] = {}
        actors = _actor_entities(title.cast or [])
        if actors:
            relations[EntityRole.ACTOR] = actors

        distributor = getattr(title, "distributor", None) or getattr(title, "studio", None)
        if distributor:
            relations[EntityRole.STUDIO] = [_studio_entity(distributor)]

        return ProviderMatch(
            provider=self.name,
            confidence=confidence,
            signals=Signals(
                title=title.title,
                year=int(title.year) if getattr(title, "year", None) else None,
                runtime=runtime,
                medium=MediaType.SHORT_FILM if getattr(title, "is_webscene", False)
                       else MediaType.MOVIE,
            ),
            external_ids=external_ids,
            relations=relations,
        )

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Re-fetch a known ``iafd_title_uuid`` and fill missing attributes."""
        uuid = external_ids.extra.get("iafd_title_uuid")
        if not uuid:
            return None
        # Only re-fetch if we're missing key fields
        if "iafd_title_url" in external_ids.extra and "iafd_distributor" in external_ids.extra:
            return None

        import pyiafd as _iafd
        try:
            title = _iafd.get_title(uuid)
        except Exception as exc:
            LOG.warning("iafd: enrich title %r: %s", uuid, exc)
            return None

        return _title_external_ids(title)


# ---------------------------------------------------------------------------
# Module-level performer enrichment helper
# ---------------------------------------------------------------------------

def enrich_performer_entity(entity: ProviderEntity) -> ProviderEntity:
    """Resolve a performer against IAFD and merge bio data into the entity.

    Resolution order:

    1. If ``extra["iafd_performer_uuid"]`` is already set, re-fetch by UUID.
    2. Otherwise search by name; exact match first, then best fuzzy ≥ 0.80.

    The entity is returned unchanged when:

    - ``pyiafd`` is not installed
    - no match is found
    - the network request fails

    Keys written:  see :mod:`pyiafd.ids` for the full list.
    """
    try:
        import pyiafd as _iafd
        from pyiafd.ids import performer_to_extra
    except ImportError:
        return entity

    if not entity.name and not entity.external_ids.extra.get("iafd_performer_uuid"):
        return entity

    # Short-circuit: UUID + birthday both present — already fully enriched
    uuid = entity.external_ids.extra.get("iafd_performer_uuid")
    if uuid and "iafd_birthday" in entity.external_ids.extra:
        return entity

    # UUID present but not yet enriched — re-fetch by UUID
    if uuid and "iafd_birthday" not in entity.external_ids.extra:
        try:
            performer = _iafd.get_performer(uuid)
            extra = performer_to_extra(performer)
            merged = entity.external_ids.merge(ExternalIds(extra=extra))
            return entity.model_copy(update={"external_ids": merged})
        except Exception as exc:
            LOG.warning("iafd: get_performer(%r): %s", uuid, exc)
            return entity

    # Name-based search
    if not entity.name:
        return entity

    try:
        results = _iafd.search_performers(entity.name)
    except Exception as exc:
        LOG.warning("iafd: search_performers(%r): %s", entity.name, exc)
        return entity

    if not results:
        return entity

    name_lower = entity.name.lower()
    match = next((r for r in results if r.name.lower() == name_lower), None)

    if match is None:
        scored = sorted(
            results,
            key=lambda r: difflib.SequenceMatcher(None, name_lower, r.name.lower()).ratio(),
            reverse=True,
        )
        top_ratio = difflib.SequenceMatcher(None, name_lower, scored[0].name.lower()).ratio()
        if scored and top_ratio >= 0.80:
            match = scored[0]

    if match is None:
        return entity

    try:
        performer = _iafd.get_performer(match.id)
    except Exception as exc:
        LOG.warning("iafd: get_performer(%r) for %r: %s", match.id, match.name, exc)
        return entity

    extra = performer_to_extra(performer)
    merged = entity.external_ids.merge(ExternalIds(extra=extra))
    return entity.model_copy(update={"external_ids": merged})


register(IAFDProvider())
