"""StashDB metadata provider.

StashDB (stashdb.org) is a community-maintained Stash-Box instance that
carries performer biographies, scene metadata, and cross-source URL links
for the adult film industry.  All queries require a registered account API
key (``STASHDB_API_KEY`` env var or ``~/.config/pystashdb/config.toml``).

Scene lookup
------------
:meth:`StashDBProvider.lookup` searches StashDB by title and returns a
:class:`ProviderMatch` with:

- Confidence up to 0.85.
- Signals: title, year, runtime, studio.
- ACTOR relations — one :class:`ProviderEntity` per cast member, each
  carrying ``stashdb_id`` and ``stashdb_url`` for later enrichment.
- A STUDIO relation when present.
- ``external_ids.extra["stashdb_scene_id"]`` for re-fetch.

Performer enrichment
--------------------
:func:`enrich_performer_entity` resolves a performer by name (or existing
``stashdb_id``) and writes ``stashdb_*`` keys into ``external_ids.extra``.
Cross-source URLs (IAFD, FreeOnes) embedded in StashDB's URL list are also
extracted to their own provider keys.

Fast path via ThePornDB social links
-------------------------------------
When a performer entity already has a ``stashdb_url`` set by a previous
ThePornDB enrichment step, the UUID is extracted from that URL and used to
fetch the full profile directly without a name search.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import Dict, List, Optional

from mediavocab import MediaType, PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity

LOG = logging.getLogger("metadatarr.resolve.providers.pystashdb")

_MEDIA = {MediaType.MOVIE, MediaType.SHORT_FILM}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _best_match(query: str, items, attr: str = "title", threshold: float = 0.60):
    """Return the item whose ``attr`` best matches ``query``, or None."""
    if not items:
        return None
    ql = query.lower()
    exact = next((x for x in items if getattr(x, attr, "").lower() == ql), None)
    if exact:
        return exact
    scored = sorted(items, key=lambda x: _ratio(ql, getattr(x, attr, "").lower()), reverse=True)
    if scored and _ratio(ql, getattr(scored[0], attr, "").lower()) >= threshold:
        return scored[0]
    return None


def _uuid_from_stashdb_url(url: str) -> Optional[str]:
    m = re.search(r"/performers/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", url or "")
    return m.group(1) if m else None


def _actor_entities(performers) -> List[ProviderEntity]:
    entities = []
    for credit in performers:
        p = credit.performer
        if not p.name:
            continue
        extra: dict = {}
        if p.id:
            extra["stashdb_id"] = p.id
            extra["stashdb_url"] = f"https://stashdb.org/performers/{p.id}"
        entities.append(ProviderEntity(
            role=EntityRole.ACTOR,
            name=str(credit),
            external_ids=ExternalIds(extra=extra),
        ))
    return entities


def _studio_entity(name: str) -> ProviderEntity:
    return ProviderEntity(
        role=EntityRole.STUDIO,
        name=name,
        external_ids=ExternalIds(),
    )


def _scene_external_ids(scene) -> ExternalIds:
    try:
        from pystashdb.ids import scene_to_extra
        return ExternalIds(extra=scene_to_extra(scene))
    except ImportError:
        return ExternalIds(extra={"stashdb_scene_id": scene.id})


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class StashDBProvider(MetadataProvider):
    """StashDB scene lookup and scene enrichment."""

    name = "stashdb"
    media = _MEDIA
    playback_type = {PlaybackType.VIDEO}

    def is_available(self) -> bool:
        try:
            import pystashdb  # noqa: F401
            return True
        except ImportError:
            return False

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        """Search StashDB by title and return the best match."""
        if not signals.title:
            return None
        if signals.medium and signals.medium not in _MEDIA:
            return None

        try:
            import pystashdb as _stash
        except ImportError:
            return None

        try:
            results = _stash.search_scenes(signals.title, limit=10)
        except Exception as exc:
            LOG.warning("stashdb: search_scenes(%r) failed: %s", signals.title, exc)
            return None

        if not results:
            return None

        best = _best_match(signals.title, results, attr="title", threshold=0.55)
        if best is None:
            return None

        ratio = _ratio(signals.title, best.title)

        if signals.year and best.release_year:
            year_hits = [s for s in results if s.release_year == signals.year]
            if year_hits:
                yb = _best_match(signals.title, year_hits, attr="title", threshold=0.45)
                if yb:
                    best = yb
                    ratio = _ratio(signals.title, best.title)

        # Fetch full scene details
        try:
            scene = _stash.get_scene(best.id)
        except Exception as exc:
            LOG.warning("stashdb: get_scene(%r) failed: %s", best.id, exc)
            # Use search result as-is
            scene = best

        confidence = 0.55 + 0.25 * ratio
        if signals.year and scene.release_year:
            if scene.release_year == signals.year:
                confidence = min(confidence + 0.10, 0.85)
        confidence = min(confidence, 0.85)

        runtime: Optional[float] = None
        if scene.duration:
            runtime = float(scene.duration) / 60.0

        external_ids = _scene_external_ids(scene)

        relations: Dict[EntityRole, List[ProviderEntity]] = {}
        actors = _actor_entities(scene.performers or [])
        if actors:
            relations[EntityRole.ACTOR] = actors
        if scene.studio:
            relations[EntityRole.STUDIO] = [_studio_entity(scene.studio.name)]

        return ProviderMatch(
            provider=self.name,
            confidence=confidence,
            signals=Signals(
                title=scene.title or signals.title,
                year=scene.release_year,
                runtime=runtime,
                medium=MediaType.SHORT_FILM,
            ),
            external_ids=external_ids,
            relations=relations,
        )

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Re-fetch a known ``stashdb_scene_id`` and fill missing attributes."""
        scene_id = external_ids.extra.get("stashdb_scene_id")
        if not scene_id:
            return None
        if "stashdb_scene_url" in external_ids.extra and "stashdb_scene_studio" in external_ids.extra:
            return None

        try:
            import pystashdb as _stash
            scene = _stash.get_scene(scene_id)
        except Exception as exc:
            LOG.warning("stashdb: enrich scene %r: %s", scene_id, exc)
            return None

        return _scene_external_ids(scene)


# ---------------------------------------------------------------------------
# Module-level performer enrichment helper
# ---------------------------------------------------------------------------

def enrich_performer_entity(entity: ProviderEntity) -> ProviderEntity:
    """Resolve a performer against StashDB and merge bio data into the entity.

    Resolution order:

    1. If ``extra["stashdb_id"]`` is already set, re-fetch by UUID.
    2. If ``extra["stashdb_url"]`` is set (e.g. from ThePornDB social links),
       extract the UUID from the URL and re-fetch.
    3. Otherwise search by name; exact match first, then best fuzzy >= 0.75.

    The entity is returned unchanged when:

    - ``pystashdb`` is not installed
    - no match is found
    - the network request fails
    - the performer is already fully enriched (``stashdb_id`` + ``stashdb_birthday`` both present)

    Keys written: see :mod:`pystashdb.ids` for the full reference.
    """
    try:
        import pystashdb as _stash
        from pystashdb.ids import performer_to_extra
    except ImportError:
        return entity

    if not entity.name and not entity.external_ids.extra.get("stashdb_id"):
        return entity

    extra = entity.external_ids.extra

    # Short-circuit: already fully enriched
    if extra.get("stashdb_id") and extra.get("stashdb_birthday"):
        return entity

    # Determine UUID from existing keys
    uuid: Optional[str] = extra.get("stashdb_id")

    if not uuid:
        stashdb_url = extra.get("stashdb_url", "")
        if stashdb_url:
            uuid = _uuid_from_stashdb_url(stashdb_url)

    # Fast path: UUID known — fetch directly
    if uuid:
        try:
            performer = _stash.get_performer(uuid)
            new_extra = performer_to_extra(performer)
            merged = entity.external_ids.merge(ExternalIds(extra=new_extra))
            return entity.model_copy(update={"external_ids": merged})
        except Exception as exc:
            LOG.warning("stashdb: get_performer(%r): %s", uuid, exc)
            return entity

    # Name-based search
    if not entity.name:
        return entity

    try:
        results = _stash.search_performers(entity.name, limit=10)
    except Exception as exc:
        LOG.warning("stashdb: search_performers(%r): %s", entity.name, exc)
        return entity

    if not results:
        return entity

    name_lower = entity.name.lower()
    match = next((p for p in results if p.name.lower() == name_lower), None)

    if match is None:
        scored = sorted(
            results,
            key=lambda p: difflib.SequenceMatcher(None, name_lower, p.name.lower()).ratio(),
            reverse=True,
        )
        top = scored[0]
        ratio = difflib.SequenceMatcher(None, name_lower, top.name.lower()).ratio()
        if ratio >= 0.75:
            match = top

    if match is None:
        return entity

    try:
        performer = _stash.get_performer(match.id)
    except Exception as exc:
        LOG.warning("stashdb: get_performer(%r) for %r: %s", match.id, match.name, exc)
        return entity

    new_extra = performer_to_extra(performer)
    merged = entity.external_ids.merge(ExternalIds(extra=new_extra))
    return entity.model_copy(update={"external_ids": merged})


register(StashDBProvider())
