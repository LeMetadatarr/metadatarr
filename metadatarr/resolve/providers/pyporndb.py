"""ThePornDB metadata provider.

ThePornDB is a community-maintained database of adult content covering
performers, scenes, movies, and studios.  It is the primary metadata source
for the Stash media manager and carries stable UUIDs for all entities.

Title lookup
------------
:meth:`ThePornDBProvider.lookup` searches ThePornDB by title and returns a
:class:`ProviderMatch` with:

- Confidence up to **0.88** (boosted when year matches).
- ACTOR relations — one :class:`ProviderEntity` per cast member, each
  carrying ``extra["theporndb_uuid"]`` for later enrichment.
- A STUDIO relation for the site/network when present.
- ``external_ids.extra["theporndb_scene_uuid"]`` — stable UUID for the title.

Performer enrichment
--------------------
:func:`enrich_performer_entity` resolves a performer by name (or existing
``theporndb_uuid``) and writes physical stats and social links into
``external_ids.extra``.  See :mod:`pyporndb.ids` for the complete key list.

Title enrichment
----------------
:meth:`ThePornDBProvider.enrich` re-fetches a known ``theporndb_scene_uuid``
to fill missing attributes.
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

LOG = logging.getLogger("metadatarr.resolve.providers.pyporndb")

_MEDIA = {MediaType.MOVIE, MediaType.SHORT_FILM}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _best_result(query: str, results, *, name_attr: str = "name", threshold: float = 0.60):
    """Return the best fuzzy-matching result from a list, or None."""
    if not results:
        return None
    ql = query.lower()
    exact = next((r for r in results if getattr(r, name_attr, "").lower() == ql), None)
    if exact:
        return exact
    scored = sorted(results, key=lambda r: _ratio(ql, getattr(r, name_attr, "").lower()), reverse=True)
    if scored and _ratio(ql, getattr(scored[0], name_attr, "").lower()) >= threshold:
        return scored[0]
    return None


def _actor_entities_full(performers) -> List[ProviderEntity]:
    """Build ACTOR ProviderEntities from full Performer objects (with social links)."""
    entities = []
    for perf in performers:
        name = getattr(perf, "name", "") or ""
        if not name.strip():
            continue
        try:
            from pyporndb.ids import performer_to_extra
            extra = performer_to_extra(perf)
        except Exception:
            extra = {}
            if getattr(perf, "uuid", None):
                extra["theporndb_uuid"] = perf.uuid
        entities.append(ProviderEntity(
            role=EntityRole.ACTOR,
            name=name.strip(),
            external_ids=ExternalIds(extra=extra),
        ))
    return entities


def _actor_entities(performers) -> List[ProviderEntity]:
    """Build ACTOR ProviderEntities from a list of PerformerRef objects."""
    entities = []
    for ref in performers:
        name = getattr(ref, "name", "") or ""
        if not name.strip():
            continue
        extra: dict = {}
        if getattr(ref, "uuid", None):
            extra["theporndb_uuid"] = ref.uuid
        if getattr(ref, "id", None):
            extra["theporndb_id"] = str(ref.id)
        if getattr(ref, "slug", None):
            extra["theporndb_slug"] = ref.slug
        if getattr(ref, "poster_url", None):
            extra["theporndb_photo_url"] = ref.poster_url
        entities.append(ProviderEntity(
            role=EntityRole.ACTOR,
            name=name.strip(),
            external_ids=ExternalIds(extra=extra),
        ))
    return entities


def _studio_entity(name: str) -> ProviderEntity:
    return ProviderEntity(
        role=EntityRole.STUDIO,
        name=name.strip(),
        external_ids=ExternalIds(),
    )


def _scene_external_ids(scene) -> ExternalIds:
    try:
        from pyporndb.ids import scene_to_extra
        return ExternalIds(extra=scene_to_extra(scene))
    except ImportError:
        extra = {}
        if getattr(scene, "uuid", None):
            extra["theporndb_scene_uuid"] = scene.uuid
        return ExternalIds(extra=extra)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class ThePornDBProvider(MetadataProvider):
    """ThePornDB scene lookup and enrichment."""

    name = "theporndb"
    media = _MEDIA
    playback_type = {PlaybackType.VIDEO}

    def is_available(self) -> bool:
        try:
            import pyporndb  # noqa: F401
            return True
        except ImportError:
            return False

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        """Search ThePornDB by title and return the best match."""
        if not signals.title:
            return None
        if signals.medium and signals.medium not in _MEDIA:
            return None

        try:
            import pyporndb as _pdb
        except ImportError:
            return None

        try:
            results = list(_pdb.list_scenes(max_pages=1))
            # Filter by title similarity
            results = [s for s in results if _ratio(signals.title, s.title) >= 0.45]
        except Exception as exc:
            LOG.warning("theporndb: list_scenes failed: %s", exc)
            return None

        if not results:
            return None

        best = _best_result(signals.title, results, name_attr="title", threshold=0.60)
        if best is None:
            return None

        ratio = _ratio(signals.title, best.title or "")

        try:
            from pyporndb.scenes import get_scene_with_performers
            scene, performers = get_scene_with_performers(best.uuid)
        except Exception as exc:
            LOG.warning("theporndb: get_scene_with_performers(%r) failed: %s", best.uuid, exc)
            try:
                scene = _pdb.get_scene(best.uuid)
                performers = []
            except Exception as exc2:
                LOG.warning("theporndb: get_scene(%r) failed: %s", best.uuid, exc2)
                return None

        # Confidence
        confidence = 0.55 + 0.28 * ratio
        if signals.year and scene.release_year:
            if str(scene.release_year) == str(signals.year):
                confidence = min(confidence + 0.10, 0.88)
        confidence = min(confidence, 0.88)

        runtime: Optional[float] = None
        if scene.duration:
            runtime = scene.duration / 60.0

        external_ids = _scene_external_ids(scene)

        relations: Dict[EntityRole, List[ProviderEntity]] = {}
        # Use full Performer objects when available (carry social/cross-source links)
        if performers:
            actors = _actor_entities_full(performers)
        else:
            actors = _actor_entities(scene.performers or [])
        if actors:
            relations[EntityRole.ACTOR] = actors

        site_name = (scene.site.network_name or scene.site.name) if scene.site else ""
        if site_name:
            relations[EntityRole.STUDIO] = [_studio_entity(site_name)]

        return ProviderMatch(
            provider=self.name,
            confidence=confidence,
            signals=Signals(
                title=scene.title,
                year=scene.release_year,
                runtime=runtime,
                medium=MediaType.SHORT_FILM,
            ),
            external_ids=external_ids,
            relations=relations,
        )

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Re-fetch a known ``theporndb_scene_uuid`` and fill missing fields."""
        uuid = external_ids.extra.get("theporndb_scene_uuid")
        if not uuid:
            return None
        if "theporndb_scene_date" in external_ids.extra:
            return None  # already enriched

        try:
            import pyporndb as _pdb
        except ImportError:
            return None

        try:
            scene = _pdb.get_scene(uuid)
        except Exception as exc:
            LOG.warning("theporndb: enrich scene %r: %s", uuid, exc)
            return None

        return _scene_external_ids(scene)


# ---------------------------------------------------------------------------
# Module-level performer enrichment helper
# ---------------------------------------------------------------------------

def enrich_performer_entity(entity: ProviderEntity) -> ProviderEntity:
    """Resolve a performer against ThePornDB and merge bio data.

    Performer data is sourced from scenes: the function searches recent
    scenes for the named performer, extracts their full ``Performer`` object
    (which includes physical stats and cross-source links), and merges it
    into the entity.

    Resolution order:

    1. If ``extra["theporndb_uuid"]`` is already set and bio is present,
       short-circuit (already enriched).
    2. Search recent scenes by performer name.  The first scene carrying
       a matching performer is used.
    3. Merge physical stats, social links, and cross-source URLs into the
       entity's extra dict.

    Cross-source links added when available:

    - ``iafd_url`` / ``iafd_performer_uuid`` — for IAFD cross-lookup
    - ``freeones_url`` — for FreeOnes cross-lookup
    - ``boobpedia_url`` / ``boobpedia_slug`` — for Boobpedia cross-lookup
    - ``stashdb_url`` — for StashDB cross-lookup

    The entity is returned unchanged when:

    - ``pyporndb`` is not installed
    - no match is found in the recent scene listing
    - the network request fails

    Keys written: see :mod:`pyporndb.ids` for the full list.
    """
    try:
        import pyporndb as _pdb
        from pyporndb.ids import (
            performer_to_extra,
            iafd_uuid_from_url,
            freeones_slug_from_url,
            boobpedia_slug_from_url,
        )
    except ImportError:
        return entity

    if not entity.name and not entity.external_ids.extra.get("theporndb_uuid"):
        return entity

    # Short-circuit: already fully enriched
    uuid = entity.external_ids.extra.get("theporndb_uuid")
    if uuid and "theporndb_birthday" in entity.external_ids.extra:
        return entity

    performer = None

    # Search for performer in recent scenes
    if entity.name:
        try:
            scenes = list(_pdb.scenes_by_performer_name(entity.name, max_pages=1))
        except Exception as exc:
            LOG.warning("theporndb: scenes_by_performer_name(%r): %s", entity.name, exc)
            scenes = []

        name_lower = entity.name.lower()
        for scene in scenes:
            # Try extracting full Performer objects from scene detail
            try:
                from pyporndb.scenes import get_scene_with_performers
                from pyporndb.performer import extract_performers_from_scene_data
                _, perfs = get_scene_with_performers(scene.uuid)
            except Exception:
                perfs = []
            for p in perfs:
                if p.name.lower() == name_lower or (
                    uuid and p.uuid == uuid
                ):
                    performer = p
                    break
            if performer:
                break

        # Fall back to matching PerformerRef from scene listing
        if performer is None:
            for scene in scenes:
                for ref in (scene.performers or []):
                    if ref.name.lower() == name_lower or (uuid and ref.uuid == uuid):
                        performer = ref
                        break
                if performer:
                    break

    if performer is None:
        return entity

    extra = performer_to_extra(performer)

    # Cross-source link extraction
    social = getattr(performer, "social", None)
    if social:
        if social.iafd_url:
            iafd_uuid = iafd_uuid_from_url(social.iafd_url)
            if iafd_uuid:
                extra["iafd_performer_uuid"] = iafd_uuid
        if social.freeones_url:
            fo_slug = freeones_slug_from_url(social.freeones_url)
            if fo_slug:
                extra["freeones_url"] = f"https://www.freeones.com/{fo_slug}/bio"
        if social.boobpedia_url:
            bp_slug = boobpedia_slug_from_url(social.boobpedia_url)
            if bp_slug:
                extra["boobpedia_slug"] = bp_slug

    merged = entity.external_ids.merge(ExternalIds(extra=extra))
    return entity.model_copy(update={"external_ids": merged})


register(ThePornDBProvider())
