"""The Lord of Porn metadata provider.

thelordofporn.com is a review and index site covering performers, networks,
individual porn sites, sex cams, porn series, versus battles, and parodies.

Title lookup
------------
Two content types carry enough structured data to support :meth:`lookup`:

1. **Porn parodies** (``MediaType.MOVIE`` / ``MediaType.SHORT_FILM``) —
   titles, studio, full cast list, and a buy/stream link.  Parody titles are
   highly distinctive (e.g. "Star Wars XXX: A Porn Parody") so false-positive
   collisions with mainstream content are rare.  ACTOR relations are emitted
   from the ``starring`` list; a STUDIO relation is emitted from the
   ``studio`` field.  Confidence is capped at **0.60** — TLoP is a review
   site, not an authoritative filmography.

2. **Porn series** (``MediaType.EPISODIC_SERIES``) — title and genre
   categories.  Confidence is capped at **0.45** because series carry less
   structured data than parodies.

Entity enrichment
-----------------
Enrichment helpers (module-level functions) resolve performers and studios
by name against the TLoP index and merge profile data into a
:class:`ProviderEntity`.

``enrich_performer_entity`` writes physical attributes
(hair_color, ethnicity, measurements, …) via
:func:`~pylordofporn.ids.performer_to_extra`.

``enrich_studio_entity`` resolves a studio name against networks first,
then individual sites, and writes the real affiliate/visit URL alongside
the slug.

``enrich()`` re-fetches a known TLoP slug when the corresponding attribute
keys are absent (e.g. a performer slug landed from FreeOnes cross-linking).

Canonical identifiers
---------------------
TLoP slugs are stable WordPress slugs unique within their content-type
namespace.  See :mod:`pylordofporn.ids` for the complete key reference and
converter functions.

All IDs land in ``ExternalIds.extra`` — there are no first-class
``ExternalIds`` fields for TLoP data.

Keys written
------------
Performer:  ``tlop_performer_slug``, ``tlop_performer_url``,
            ``tlop_performer_photo``, ``tlop_performer_twitter``,
            ``tlop_performer_aliases``, ``tlop_performer_career_start``,
            ``tlop_performer_birth_year``, ``tlop_performer_place_of_birth``,
            ``tlop_hair_color``, ``tlop_ethnicity``, ``tlop_boob_size``,
            ``tlop_ass_size``, ``tlop_height_class``, ``tlop_weight_class``,
            ``tlop_age_group``, ``tlop_pierced``, ``tlop_tattooed``,
            ``tlop_measurements``, ``tlop_height_cm``, ``tlop_weight_kg``

Network:    ``tlop_network_slug``, ``tlop_network_url``,
            ``tlop_network_photo``, ``tlop_network_visit_url``,
            ``tlop_network_discount``, ``tlop_network_categories``

Site:       ``tlop_site_slug``, ``tlop_site_url``, ``tlop_site_photo``,
            ``tlop_site_visit_url``, ``tlop_site_discount``,
            ``tlop_site_categories``

Parody:     ``tlop_parody_slug``, ``tlop_parody_url``,
            ``tlop_parody_photo``, ``tlop_parody_studio``,
            ``tlop_parody_based_on``, ``tlop_parody_visit_url``,
            ``tlop_parody_categories``

Series:     ``tlop_series_slug``, ``tlop_series_url``,
            ``tlop_series_photo``, ``tlop_series_categories``
"""
from __future__ import annotations

import difflib
import json
import logging
from typing import Dict, List, Optional

from mediavocab import MediaType, PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity

LOG = logging.getLogger("metadatarr.resolve.providers.pylordofporn")

_PARODY_MEDIA  = {MediaType.MOVIE, MediaType.SHORT_FILM}
_SERIES_MEDIA  = {MediaType.EPISODIC_SERIES, MediaType.TV}
_LOOKUP_MEDIA  = _PARODY_MEDIA | _SERIES_MEDIA

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _best_match(query: str, results, *, threshold: float = 0.75):
    """Return the result whose name best matches *query*, or None.

    Matching strategy (highest priority first):
    1. Exact case-insensitive name match.
    2. Query is a prefix of the result name (e.g. "Brazzers" → "Brazzers Network").
    3. Result name is a prefix of query.
    4. SequenceMatcher ratio ≥ threshold.
    """
    if not results:
        return None
    ql = query.lower()

    for r in results:
        rl = r.name.lower()
        if rl == ql:
            return r

    # Prefix containment — handles "Brazzers" ↔ "Brazzers Network"
    for r in results:
        rl = r.name.lower()
        if rl.startswith(ql) or ql.startswith(rl):
            return r

    scored = sorted(results, key=lambda r: _ratio(ql, r.name.lower()), reverse=True)
    if scored and _ratio(ql, scored[0].name.lower()) >= threshold:
        return scored[0]
    return None


def _actor_entities(starring: List[str]) -> List[ProviderEntity]:
    """Build ACTOR ProviderEntity records from a cast name list."""
    entities = []
    for name in starring:
        name = name.strip()
        if not name:
            continue
        entities.append(ProviderEntity(
            role=EntityRole.ACTOR,
            name=name,
            external_ids=ExternalIds(),
        ))
    return entities


def _studio_entity(studio_name: str, *, extra: Optional[dict] = None) -> ProviderEntity:
    """Build a STUDIO ProviderEntity for *studio_name*."""
    ext = ExternalIds(extra=extra or {})
    return ProviderEntity(role=EntityRole.STUDIO, name=studio_name, external_ids=ext)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class LordOfPornProvider(MetadataProvider):
    """TLoP enrichment + parody/series title lookup."""

    name = "lordofporn"
    media: set = set()         # declared below per-method; provider handles all
    playback_type: set = set()

    def is_available(self) -> bool:
        try:
            import pylordofporn  # noqa: F401
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # lookup: parodies + series
    # ------------------------------------------------------------------

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        """Return a match for parody or series titles.

        Routing:
        - ``MediaType.MOVIE`` / ``SHORT_FILM`` → search parodies
        - ``MediaType.EPISODIC_SERIES`` / ``TV``  → search series
        - ``None`` medium → try parodies first, then series (lower confidence)
        """
        if not signals.title:
            return None
        if signals.medium and signals.medium not in _LOOKUP_MEDIA:
            return None

        want_parody = (not signals.medium) or signals.medium in _PARODY_MEDIA
        want_series = (not signals.medium) or signals.medium in _SERIES_MEDIA

        if want_parody:
            match = self._lookup_parody(signals)
            if match:
                return match

        if want_series:
            match = self._lookup_series(signals)
            if match:
                return match

        return None

    def _lookup_parody(self, signals: Signals) -> Optional[ProviderMatch]:
        try:
            from pylordofporn import search_parodies, get_parody
            from pylordofporn.ids import parody_to_extra
        except ImportError:
            return None

        try:
            results = search_parodies(signals.title or "")
        except Exception as exc:
            LOG.warning("tlop: search_parodies(%r) failed: %s", signals.title, exc)
            return None

        card = _best_match(signals.title or "", results, threshold=0.70)
        if card is None:
            return None

        ratio = _ratio(signals.title or "", card.name)

        try:
            parody = get_parody(card.slug)
        except Exception as exc:
            LOG.warning("tlop: get_parody(%r) failed: %s", card.slug, exc)
            return None

        # Confidence: 0.40 base + bonus for close title match.
        # Never exceeds 0.60 — TLoP is a review index, not an authoritative DB.
        confidence = min(0.40 + 0.20 * ratio, 0.60)

        external_ids = ExternalIds(extra=parody_to_extra(parody))

        # Relations: cast as ACTOR, studio as STUDIO
        relations: Dict[EntityRole, List[ProviderEntity]] = {}
        actors = _actor_entities(parody.starring)
        if actors:
            relations[EntityRole.ACTOR] = actors
        if parody.studio:
            relations[EntityRole.STUDIO] = [_studio_entity(parody.studio)]

        return ProviderMatch(
            provider=self.name,
            confidence=confidence,
            signals=Signals.as_observation(
                title=parody.name,
                medium=MediaType.MOVIE,
                content_genres=parody.categories or [],
            ),
            external_ids=external_ids,
            relations=relations,
        )

    def _lookup_series(self, signals: Signals) -> Optional[ProviderMatch]:
        try:
            from pylordofporn import search_series, get_series
            from pylordofporn.ids import series_to_extra
        except ImportError:
            return None

        try:
            results = search_series(signals.title or "")
        except Exception as exc:
            LOG.warning("tlop: search_series(%r) failed: %s", signals.title, exc)
            return None

        card = _best_match(signals.title or "", results, threshold=0.75)
        if card is None:
            return None

        ratio = _ratio(signals.title or "", card.name)

        try:
            series = get_series(card.slug)
        except Exception as exc:
            LOG.warning("tlop: get_series(%r) failed: %s", card.slug, exc)
            return None

        # Series carry less data → lower confidence ceiling
        confidence = min(0.30 + 0.15 * ratio, 0.45)

        external_ids = ExternalIds(extra=series_to_extra(series))

        return ProviderMatch(
            provider=self.name,
            confidence=confidence,
            signals=Signals.as_observation(
                title=series.name,
                medium=MediaType.EPISODIC_SERIES,
                content_genres=series.categories or [],
            ),
            external_ids=external_ids,
        )

    # ------------------------------------------------------------------
    # enrich: re-fetch known TLoP slugs and fill missing fields
    # ------------------------------------------------------------------

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Refetch a known TLoP slug and fill in missing attribute fields."""
        extra = external_ids.extra

        # Performer — re-fetch if slug present but attributes not yet populated
        if extra.get("tlop_performer_slug") and "tlop_hair_color" not in extra:
            return self._enrich_performer(extra["tlop_performer_slug"])

        # Parody — re-fetch if slug present but studio missing
        if extra.get("tlop_parody_slug") and "tlop_parody_studio" not in extra:
            return self._enrich_parody(extra["tlop_parody_slug"])

        # Series — re-fetch if slug present but categories missing
        if extra.get("tlop_series_slug") and "tlop_series_categories" not in extra:
            return self._enrich_series(extra["tlop_series_slug"])

        # Network — re-fetch if slug present but visit URL missing
        if extra.get("tlop_network_slug") and "tlop_network_visit_url" not in extra:
            return self._enrich_network(extra["tlop_network_slug"])

        # Site — re-fetch if slug present but visit URL missing
        if extra.get("tlop_site_slug") and "tlop_site_visit_url" not in extra:
            return self._enrich_site(extra["tlop_site_slug"])

        return None

    def _enrich_performer(self, slug: str) -> Optional[ExternalIds]:
        try:
            from pylordofporn import get_performer
            from pylordofporn.ids import performer_to_extra
            p = get_performer(slug)
            return ExternalIds(extra=performer_to_extra(p))
        except Exception as exc:
            LOG.warning("tlop: enrich performer %r: %s", slug, exc)
            return None

    def _enrich_parody(self, slug: str) -> Optional[ExternalIds]:
        try:
            from pylordofporn import get_parody
            from pylordofporn.ids import parody_to_extra
            return ExternalIds(extra=parody_to_extra(get_parody(slug)))
        except Exception as exc:
            LOG.warning("tlop: enrich parody %r: %s", slug, exc)
            return None

    def _enrich_series(self, slug: str) -> Optional[ExternalIds]:
        try:
            from pylordofporn import get_series
            from pylordofporn.ids import series_to_extra
            return ExternalIds(extra=series_to_extra(get_series(slug)))
        except Exception as exc:
            LOG.warning("tlop: enrich series %r: %s", slug, exc)
            return None

    def _enrich_network(self, slug: str) -> Optional[ExternalIds]:
        try:
            from pylordofporn import get_network
            from pylordofporn.ids import network_to_extra
            return ExternalIds(extra=network_to_extra(get_network(slug)))
        except Exception as exc:
            LOG.warning("tlop: enrich network %r: %s", slug, exc)
            return None

    def _enrich_site(self, slug: str) -> Optional[ExternalIds]:
        try:
            from pylordofporn import get_site
            from pylordofporn.ids import site_to_extra
            return ExternalIds(extra=site_to_extra(get_site(slug)))
        except Exception as exc:
            LOG.warning("tlop: enrich site %r: %s", slug, exc)
            return None


# ---------------------------------------------------------------------------
# Module-level entity enrichment helpers
# ---------------------------------------------------------------------------

def enrich_performer_entity(entity: ProviderEntity) -> ProviderEntity:
    """Resolve a performer by name against TLoP and merge profile data.

    Writes physical attributes (hair_color, ethnicity, measurements, …),
    career data (career_start, birth_year, place_of_birth), and media
    links (photo_url, twitter) into the entity's ``external_ids``.

    The entity is returned unchanged when pylordofporn is not installed,
    the name produces no results, or the fuzzy-match ratio is below 0.75.
    """
    try:
        from pylordofporn import search_performers, get_performer
        from pylordofporn.ids import performer_to_extra
    except ImportError:
        return entity

    if not entity.name:
        return entity

    # Short-circuit: already have a slug — just enrich
    slug = entity.external_ids.extra.get("tlop_performer_slug")
    if slug and "tlop_hair_color" not in entity.external_ids.extra:
        try:
            p = get_performer(slug)
            extra = performer_to_extra(p)
            merged = entity.external_ids.merge(ExternalIds(extra=extra))
            return entity.model_copy(update={"external_ids": merged})
        except Exception as exc:
            LOG.warning("tlop: get_performer(%r): %s", slug, exc)
            return entity

    # Name-based search
    try:
        results = search_performers(entity.name)
    except Exception as exc:
        LOG.warning("tlop: search_performers(%r): %s", entity.name, exc)
        return entity

    card = _best_match(entity.name, results, threshold=0.75)
    if card is None:
        return entity

    try:
        p = get_performer(card.slug)
    except Exception as exc:
        LOG.warning("tlop: get_performer(%r): %s", card.slug, exc)
        return entity

    extra = performer_to_extra(p)
    merged = entity.external_ids.merge(ExternalIds(extra=extra))
    return entity.model_copy(update={"external_ids": merged})


def enrich_studio_entity(entity: ProviderEntity) -> ProviderEntity:
    """Resolve a studio name against TLoP (networks first, then sites).

    Writes the real affiliate/visit URL alongside the slug, so downstream
    callers can follow through to the actual studio website rather than
    the TLoP review page.
    """
    try:
        from pylordofporn import (
            search_networks, get_network,
            search_sites,    get_site,
        )
        from pylordofporn.ids import network_to_extra, site_to_extra
    except ImportError:
        return entity

    if not entity.name:
        return entity

    # Short-circuit: already have network or site slug
    extra = entity.external_ids.extra
    if extra.get("tlop_network_slug") and "tlop_network_visit_url" not in extra:
        try:
            n = get_network(extra["tlop_network_slug"])
            merged = entity.external_ids.merge(ExternalIds(extra=network_to_extra(n)))
            return entity.model_copy(update={"external_ids": merged})
        except Exception as exc:
            LOG.warning("tlop: get_network(%r): %s", extra["tlop_network_slug"], exc)
    if extra.get("tlop_site_slug") and "tlop_site_visit_url" not in extra:
        try:
            s = get_site(extra["tlop_site_slug"])
            merged = entity.external_ids.merge(ExternalIds(extra=site_to_extra(s)))
            return entity.model_copy(update={"external_ids": merged})
        except Exception as exc:
            LOG.warning("tlop: get_site(%r): %s", extra["tlop_site_slug"], exc)

    # Name-based search — networks first
    try:
        card = _best_match(entity.name, search_networks(entity.name))
        if card:
            n = get_network(card.slug)
            merged = entity.external_ids.merge(ExternalIds(extra=network_to_extra(n)))
            return entity.model_copy(update={"external_ids": merged})
    except Exception as exc:
        LOG.warning("tlop: network search for %r: %s", entity.name, exc)

    # Fall back to individual sites
    try:
        card = _best_match(entity.name, search_sites(entity.name))
        if card:
            s = get_site(card.slug)
            merged = entity.external_ids.merge(ExternalIds(extra=site_to_extra(s)))
            return entity.model_copy(update={"external_ids": merged})
    except Exception as exc:
        LOG.warning("tlop: site search for %r: %s", entity.name, exc)

    return entity


def build_parody_match(slug: str) -> Optional[ProviderMatch]:
    """Fetch a parody by slug and return a :class:`ProviderMatch` directly.

    Useful in scripts that already know the TLoP slug (e.g. from a previous
    listing crawl) and want to hydrate a metadatarr record without going
    through the search path.

    Returns ``None`` on network or import error.
    """
    try:
        from pylordofporn import get_parody
        from pylordofporn.ids import parody_to_extra
    except ImportError:
        return None

    try:
        parody = get_parody(slug)
    except Exception as exc:
        LOG.warning("tlop: build_parody_match(%r): %s", slug, exc)
        return None

    relations: Dict[EntityRole, List[ProviderEntity]] = {}
    actors = _actor_entities(parody.starring)
    if actors:
        relations[EntityRole.ACTOR] = actors
    if parody.studio:
        relations[EntityRole.STUDIO] = [_studio_entity(parody.studio)]

    return ProviderMatch(
        provider="lordofporn",
        confidence=0.55,
        signals=Signals.as_observation(
            title=parody.name,
            medium=MediaType.MOVIE,
            content_genres=parody.categories or [],
        ),
        external_ids=ExternalIds(extra=parody_to_extra(parody)),
        relations=relations,
    )


register(LordOfPornProvider())
