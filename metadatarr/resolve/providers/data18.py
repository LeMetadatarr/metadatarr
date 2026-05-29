"""data18.com metadata provider.

data18.com is an authoritative adult database of **scenes**, **movies**,
**performers** and **studios**. Unlike a review index, its records carry exact
cast lists, studio attribution, tags, and release dates — so matches are
high-confidence when keyed by a data18 identifier.

Title lookup vs. enrichment
---------------------------
data18 search is JavaScript-driven and has no stable server-side endpoint, so
this provider does **not** discover records from a free-text title. Instead it
supports:

* :meth:`lookup` — fires only when ``signals`` already carry a data18
  identifier (``data18_scene_id`` / ``data18_movie_slug`` / ``data18_movie_id``),
  typically seeded by a prior crawl or another provider. It hydrates the full
  record and emits ACTOR + STUDIO relations.
* :meth:`enrich` — re-fetches a known data18 id/slug and fills missing fields.
* :func:`enrich_performer_entity` / :func:`enrich_studio_entity` — resolve a
  performer/studio **by name** via slug derivation (data18 slugs are the
  lower-cased, hyphenated display name) and merge profile data.
* :func:`build_scene_match` / :func:`build_movie_match` — hydrate a match
  directly from a known id, for scripts that already hold one.

Media mapping
-------------
* Movies  → :data:`MediaType.MOVIE`
* Scenes  → :data:`MediaType.SHORT_FILM`

Confidence
----------
Because lookup is keyed by an exact identifier (never a fuzzy title), matches
are high-confidence: **0.85** for movies, **0.80** for scenes.

Canonical identifiers
---------------------
See :mod:`pydata18.ids`. All ids land in ``ExternalIds.extra``:

Scene:     ``data18_scene_id``, ``data18_scene_url``,
           ``data18_scene_studio``, ``data18_scene_movie``,
           ``data18_scene_cast``, ``data18_scene_tags``
Movie:     ``data18_movie_id``, ``data18_movie_slug``, ``data18_movie_url``,
           ``data18_movie_studio``, ``data18_movie_cast``, ``data18_movie_tags``
Performer: ``data18_performer_slug``, ``data18_performer_url``,
           ``data18_performer_photo``, ``data18_performer_aliases``,
           ``data18_measurements``, ``data18_ethnicity``, ``data18_hair_color``
Studio:    ``data18_studio_slug``, ``data18_studio_url``
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from mediavocab import MediaType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity

LOG = logging.getLogger("metadatarr.resolve.providers.data18")

_LOOKUP_MEDIA = {MediaType.MOVIE, MediaType.SHORT_FILM}


# ---------------------------------------------------------------------------
# Relation builders
# ---------------------------------------------------------------------------

def _actor_entities(performers) -> List[ProviderEntity]:
    """ACTOR entities from a list of PerformerRef, carrying the data18 slug."""
    out: List[ProviderEntity] = []
    for p in performers:
        if not getattr(p, "name", ""):
            continue
        out.append(ProviderEntity(
            role=EntityRole.ACTOR,
            name=p.name,
            external_ids=ExternalIds(extra={"data18_performer_slug": p.slug}),
        ))
    return out


def _studio_entity(studio_ref) -> Optional[ProviderEntity]:
    if studio_ref is None or not getattr(studio_ref, "name", ""):
        return None
    return ProviderEntity(
        role=EntityRole.STUDIO,
        name=studio_ref.name,
        external_ids=ExternalIds(extra={"data18_studio_slug": studio_ref.slug}),
    )


def _scene_match(scene, confidence: float = 0.80) -> ProviderMatch:
    from pydata18.ids import scene_to_extra
    relations: Dict[EntityRole, List[ProviderEntity]] = {}
    actors = _actor_entities(scene.performers)
    if actors:
        relations[EntityRole.ACTOR] = actors
    studio = _studio_entity(scene.studio)
    if studio:
        relations[EntityRole.STUDIO] = [studio]
    return ProviderMatch(
        provider="data18",
        confidence=confidence,
        signals=Signals.as_observation(
            title=scene.title,
            medium=MediaType.SHORT_FILM,
            content_genres=scene.tags or [],
        ),
        external_ids=ExternalIds(extra=scene_to_extra(scene)),
        relations=relations,
    )


def _movie_match(movie, confidence: float = 0.85) -> ProviderMatch:
    from pydata18.ids import movie_to_extra
    relations: Dict[EntityRole, List[ProviderEntity]] = {}
    actors = _actor_entities(movie.performers)
    if actors:
        relations[EntityRole.ACTOR] = actors
    studio = _studio_entity(movie.studio)
    if studio:
        relations[EntityRole.STUDIO] = [studio]
    return ProviderMatch(
        provider="data18",
        confidence=confidence,
        signals=Signals.as_observation(
            title=movie.title,
            medium=MediaType.MOVIE,
            content_genres=movie.tags or [],
        ),
        external_ids=ExternalIds(extra=movie_to_extra(movie)),
        relations=relations,
    )


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class Data18Provider(MetadataProvider):
    """data18 id-keyed lookup + performer/studio enrichment."""

    name = "data18"
    media: set = set()
    playback_type: set = set()

    def is_available(self) -> bool:
        try:
            import pydata18  # noqa: F401
            return True
        except ImportError:
            return False

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        """Always ``None`` — data18 has no title-based discovery path.

        data18 search is JavaScript-driven (no stable server-side endpoint) and
        :class:`Signals` carries no identifier field, so there is no way to
        resolve a record from a free-text title. Hydration happens by id via
        :meth:`enrich`, :func:`build_scene_match`, and :func:`build_movie_match`;
        performer/studio resolution happens by name via
        :func:`enrich_performer_entity` / :func:`enrich_studio_entity`.
        """
        return None

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Re-fetch a known data18 id/slug and fill in missing fields."""
        extra = external_ids.extra

        if extra.get("data18_movie_slug") and "data18_movie_cast" not in extra:
            return self._enrich_movie(extra["data18_movie_slug"])
        if extra.get("data18_scene_id") and "data18_scene_cast" not in extra:
            return self._enrich_scene(extra["data18_scene_id"])
        if extra.get("data18_performer_slug") and "data18_measurements" not in extra:
            return self._enrich_performer(extra["data18_performer_slug"])
        return None

    def _enrich_movie(self, slug: str) -> Optional[ExternalIds]:
        try:
            from pydata18 import get_movie
            from pydata18.ids import movie_to_extra
            return ExternalIds(extra=movie_to_extra(get_movie(slug)))
        except Exception as exc:
            LOG.warning("data18: enrich movie %r: %s", slug, exc)
            return None

    def _enrich_scene(self, scene_id: str) -> Optional[ExternalIds]:
        try:
            from pydata18 import get_scene
            from pydata18.ids import scene_to_extra
            return ExternalIds(extra=scene_to_extra(get_scene(scene_id)))
        except Exception as exc:
            LOG.warning("data18: enrich scene %r: %s", scene_id, exc)
            return None

    def _enrich_performer(self, slug: str) -> Optional[ExternalIds]:
        try:
            from pydata18 import get_performer
            from pydata18.ids import performer_to_extra
            return ExternalIds(extra=performer_to_extra(get_performer(slug)))
        except Exception as exc:
            LOG.warning("data18: enrich performer %r: %s", slug, exc)
            return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def build_scene_match(scene_id) -> Optional[ProviderMatch]:
    """Fetch a scene by id and return a :class:`ProviderMatch`."""
    try:
        from pydata18 import get_scene
    except ImportError:
        return None
    try:
        return _scene_match(get_scene(scene_id))
    except Exception as exc:
        LOG.warning("data18: build_scene_match(%r): %s", scene_id, exc)
        return None


def build_movie_match(slug) -> Optional[ProviderMatch]:
    """Fetch a movie by slug/id and return a :class:`ProviderMatch`."""
    try:
        from pydata18 import get_movie
    except ImportError:
        return None
    try:
        return _movie_match(get_movie(slug))
    except Exception as exc:
        LOG.warning("data18: build_movie_match(%r): %s", slug, exc)
        return None


def enrich_performer_entity(entity: ProviderEntity) -> ProviderEntity:
    """Resolve a performer by name (slug derivation) and merge profile data.

    data18 performer slugs are the lower-cased, hyphenated display name, so the
    name resolves to a slug without a search step. Returns the entity unchanged
    when pydata18 is missing, the name is empty, or the slug 404s.
    """
    try:
        from pydata18 import get_performer
        from pydata18.performer import slugify
        from pydata18.ids import performer_to_extra
    except ImportError:
        return entity
    if not entity.name:
        return entity

    slug = entity.external_ids.extra.get("data18_performer_slug") or slugify(entity.name)
    try:
        p = get_performer(slug)
    except Exception as exc:
        LOG.warning("data18: get_performer(%r): %s", slug, exc)
        return entity

    merged = entity.external_ids.merge(ExternalIds(extra=performer_to_extra(p)))
    return entity.model_copy(update={"external_ids": merged})


def enrich_studio_entity(entity: ProviderEntity) -> ProviderEntity:
    """Resolve a studio by name (slug derivation) and merge profile data."""
    try:
        from pydata18 import get_studio
        from pydata18.studio import slugify
        from pydata18.ids import studio_to_extra
    except ImportError:
        return entity
    if not entity.name:
        return entity

    slug = entity.external_ids.extra.get("data18_studio_slug") or slugify(entity.name)
    try:
        s = get_studio(slug)
    except Exception as exc:
        LOG.warning("data18: get_studio(%r): %s", slug, exc)
        return entity

    merged = entity.external_ids.merge(ExternalIds(extra=studio_to_extra(s)))
    return entity.model_copy(update={"external_ids": merged})


register(Data18Provider())
