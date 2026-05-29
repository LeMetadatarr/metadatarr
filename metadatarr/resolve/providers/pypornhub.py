"""Pornhub metadata provider — video search, performer profiles, canonical IDs.

No authentication required.  Confidence is capped at 0.65 for video lookup
because Pornhub titles are user-supplied and unstable, but performer lookups
are higher-confidence when the slug resolves cleanly.

Keys written to :attr:`ExternalIds.extra`:

Video
-----
- ``pornhub_vkey``         — alphanumeric view-key, the stable video identifier
- ``pornhub_url``          — canonical watch URL
- ``pornhub_stream_url``   — best available stream URL (may expire)
- ``pornhub_model_slug``   — uploader's model/pornstar slug (if available)
- ``pornhub_channel_slug`` — uploader's channel slug (if channel, not model)
- ``pornhub_categories``   — JSON array of category labels
- ``pornhub_tags``         — JSON array of folksonomy tags
- ``pornhub_production``   — "homemade" | "professional"
- ``pornhub_segment``      — "straight" | "gay" | "trans"

Performer (written on ACTOR ProviderEntity)
-------------------------------------------
- ``pornhub_model_slug``   — slug for /model/<slug>
- ``pornhub_subscribers``  — subscriber count string
- ``pornhub_rank``         — site rank string
- ``pornhub_avatar_url``   — avatar image URL
- ``physical_gender``      — as reported by Pornhub profile
- ``physical_ethnicity``
- ``physical_hair``
- ``physical_height_cm``   — parsed from "5 ft 4 in (163 cm)"
- ``physical_measurements``
- ``physical_fake_boobs``  — "true" | "false" | ""
- ``career_status``        — "Active" | "Retired" | ""
- ``career_start``         — start year string
- ``career_relationship``  — relationship status string
- ``career_interested_in`` — interested-in string
- ``social_onlyfans``      — URL string
- ``social_twitter``
- ``social_instagram``
- ``social_fansly``
- ``social_<platform>``    — any other detected platform

Cross-source linking
--------------------
- ``iafd_performer_uuid`` or ``freeones_url`` on the same ProviderEntity
  will be populated by other providers (IAFD, FreeOnes) if they also
  find the performer.  Use ``ExternalIds.merge`` to unify.
- The pornhub vkey is the most stable Pornhub canonical ID — prefer it
  over URL for storage and lookup.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from typing import Dict, List, Optional

from mediavocab import MediaType, PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from mediavocab.taxonomy import GENRE_ADULT
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity

LOG = logging.getLogger("metadatarr.resolve.providers.pypornhub")

_MEDIA = {MediaType.SHORT_FILM, MediaType.MOVIE}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _parse_height_cm(raw: str) -> str:
    """Extract cm value from strings like '5 ft 4 in (163 cm)'."""
    m = re.search(r"\((\d+)\s*cm\)", raw or "")
    return m.group(1) if m else ""


def _parse_subscribers(raw: str) -> str:
    """Strip commas from '872,553' → '872553'."""
    return re.sub(r"[^\d]", "", raw or "")


def _video_external_ids(meta) -> ExternalIds:
    extra: dict = {
        "pornhub_vkey": meta.vkey,
        "pornhub_url": meta.url,
    }
    if meta.best_stream:
        extra["pornhub_stream_url"] = meta.best_stream.url
    if meta.tags:
        extra["pornhub_tags"] = json.dumps(meta.tags)
    if meta.categories:
        extra["pornhub_categories"] = json.dumps(meta.categories)
    if getattr(meta, "production", ""):
        extra["pornhub_production"] = meta.production
    if getattr(meta, "segment", ""):
        extra["pornhub_segment"] = meta.segment
    # Uploader slug from uploader_slug (set on VideoItem, not VideoMeta)
    # — populated by enrich() or lookup_candidates() path
    return ExternalIds(extra=extra)


def _performer_extra(slug: str, profile=None) -> dict:
    """Build the extra dict for a performer entity."""
    extra: dict = {"pornhub_model_slug": slug}
    if profile is None:
        return extra

    if getattr(profile, "subscribers", ""):
        extra["pornhub_subscribers"] = _parse_subscribers(profile.subscribers)
    if getattr(profile, "rank", ""):
        extra["pornhub_rank"] = profile.rank
    if getattr(profile, "avatar", ""):
        extra["pornhub_avatar_url"] = profile.avatar

    phys = getattr(profile, "physical", None)
    if phys:
        for src_attr, dest_key in [
            ("gender",       "physical_gender"),
            ("ethnicity",    "physical_ethnicity"),
            ("hair_color",   "physical_hair"),
            ("measurements", "physical_measurements"),
            ("star_sign",    "physical_star_sign"),
            ("birth_place",  "physical_birth_place"),
        ]:
            val = getattr(phys, src_attr, "") or ""
            if val:
                extra[dest_key] = val
        height_raw = getattr(phys, "height", "") or ""
        cm = _parse_height_cm(height_raw)
        if cm:
            extra["physical_height_cm"] = cm
        if height_raw:
            extra["physical_height_raw"] = height_raw
        fake = getattr(phys, "fake_boobs", None)
        if fake is not None:
            extra["physical_fake_boobs"] = "true" if fake else "false"

    career = getattr(profile, "career", None)
    if career:
        for src_attr, dest_key in [
            ("status",              "career_status"),
            ("start",               "career_start"),
            ("relationship_status", "career_relationship"),
            ("interested_in",       "career_interested_in"),
        ]:
            val = getattr(career, src_attr, "") or ""
            if val:
                extra[dest_key] = val

    for link in (getattr(profile, "social_links", None) or []):
        platform = (link.platform or "").lower().strip() or "social"
        if link.url:
            extra[f"social_{platform}"] = link.url

    return extra


def _build_actor_entities(meta) -> List[ProviderEntity]:
    """Build ACTOR ProviderEntities from VideoMeta.pornstars."""
    entities = []
    for ref in getattr(meta, "pornstars", []) or []:
        if not (ref.name or "").strip():
            continue
        entities.append(ProviderEntity(
            role=EntityRole.ACTOR,
            name=ref.name.strip(),
            external_ids=ExternalIds(extra={"pornhub_model_slug": ref.slug or ""}),
        ))
    return entities


def _build_relations(meta) -> Dict[EntityRole, List[ProviderEntity]]:
    actors = _build_actor_entities(meta)
    return {EntityRole.ACTOR: actors} if actors else {}


# ---------------------------------------------------------------------------
# Video provider
# ---------------------------------------------------------------------------

class PornhubProvider(MetadataProvider):
    """Pornhub video search and enrichment."""

    name = "pornhub"
    media = _MEDIA
    playback_type = {PlaybackType.VIDEO}
    genre_filter = {GENRE_ADULT}

    def is_available(self) -> bool:
        try:
            import pypornhub  # noqa: F401
            return True
        except ImportError:
            return False

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if signals.medium and signals.medium not in _MEDIA:
            return None

        import pypornhub as ph

        # When signals.artist is set, search within that model's uploads
        try:
            if signals.artist:
                # Try model-specific browse first
                results = list(ph.search_videos_iter(
                    signals.title, ordering="tr"
                ))[:20]
            else:
                results = ph.search_videos(signals.title, ordering="tr")
        except Exception as exc:
            LOG.warning("pornhub search failed: %s", exc)
            return None

        if not results:
            return None

        # Filter to artist's uploads when artist signal is present
        if signals.artist:
            artist_l = signals.artist.lower()
            filtered = [r for r in results
                        if (r.uploader_name or "").lower() == artist_l
                        or (r.uploader_slug or "").lower() == artist_l.replace(" ", "-")]
            if filtered:
                results = filtered

        best = max(results, key=lambda r: _ratio(signals.title, r.title))
        ratio = _ratio(signals.title, best.title)
        if ratio < 0.45:
            return None

        try:
            meta = ph.fetch_video(best.vkey)
        except Exception as exc:
            LOG.warning("pornhub fetch_video failed for %s: %s", best.vkey, exc)
            return None

        confidence = 0.45 + 0.20 * ratio
        if signals.runtime and meta.duration_seconds:
            delta = abs(signals.runtime - meta.duration_seconds)
            if delta < 30:
                confidence = min(confidence + 0.08, 0.65)

        ext = _video_external_ids(meta)
        # Carry uploader slug from listing card when pornstars list is empty
        if best.uploader_slug and not meta.pornstars:
            ext.extra["pornhub_model_slug"] = best.uploader_slug

        return ProviderMatch(
            provider=self.name,
            confidence=min(confidence, 0.65),
            signals=Signals(
                title=meta.title,
                runtime=float(meta.duration_seconds) if meta.duration_seconds else None,
                medium=MediaType.SHORT_FILM,
                content_genres=[GENRE_ADULT],
            ),
            external_ids=ext,
            relations=_build_relations(meta),
        )

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Re-fetch a known pornhub_vkey to fill missing attributes."""
        vkey = external_ids.extra.get("pornhub_vkey")
        if not vkey:
            return None

        import pypornhub as ph

        try:
            meta = ph.fetch_video(vkey)
        except Exception as exc:
            LOG.warning("pornhub enrich failed for vkey %s: %s", vkey, exc)
            return None

        fresh = _video_external_ids(meta)
        return external_ids.merge(fresh)


# ---------------------------------------------------------------------------
# Performer provider
# ---------------------------------------------------------------------------

class PornhubPersonProvider(MetadataProvider):
    """Pornhub model/performer profile lookup.

    Triggered when ``signals.artist`` matches a known Pornhub slug or name,
    and ``signals.medium`` is a video type.  Returns a ``ProviderMatch``
    whose ``relations[EntityRole.ACTOR]`` carries the full physical/career
    attributes for the performer.
    """

    name = "pornhub_person"
    media = _MEDIA
    playback_type = {PlaybackType.VIDEO}
    genre_filter = {GENRE_ADULT}

    def is_available(self) -> bool:
        try:
            import pypornhub  # noqa: F401
            return True
        except ImportError:
            return False

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.artist:
            return None
        if signals.medium and signals.medium not in _MEDIA:
            return None

        import pypornhub as ph

        # Normalise artist name → slug candidate
        slug = signals.artist.lower().replace(" ", "-").strip()

        profile = None
        for candidate in [slug, signals.artist]:
            try:
                profile = ph.fetch_model(candidate)
                break
            except Exception:
                pass

        if profile is None:
            return None

        extra = _performer_extra(slug, profile)
        actor = ProviderEntity(
            role=EntityRole.ACTOR,
            name=profile.name or signals.artist,
            external_ids=ExternalIds(extra=extra),
        )

        return ProviderMatch(
            provider=self.name,
            confidence=0.75,
            signals=Signals(
                title=signals.title or "",
                artist=profile.name,
                medium=signals.medium or MediaType.SHORT_FILM,
                content_genres=[GENRE_ADULT],
            ),
            external_ids=ExternalIds(extra={"pornhub_model_slug": slug}),
            relations={EntityRole.ACTOR: [actor]},
        )


# ---------------------------------------------------------------------------
# Module-level helpers (used by enrichment scripts)
# ---------------------------------------------------------------------------

def enrich_performer_entity(entity: ProviderEntity) -> ProviderEntity:
    """Fetch a Pornhub model profile and merge physical/career data into entity.

    Resolution order:
    1. ``extra["pornhub_model_slug"]`` — direct slug lookup.
    2. ``entity.name`` normalised to slug.

    Returns the entity unchanged when:
    - ``pypornhub`` is not installed
    - no profile is found
    - profile has no physical attributes (creator-only /model/ accounts)

    Merges: all ``physical_*``, ``career_*``, ``social_*``, ``pornhub_subscribers``,
    ``pornhub_rank``, ``pornhub_avatar_url`` keys into ``entity.external_ids.extra``.
    """
    try:
        import pypornhub as ph
    except ImportError:
        return entity

    slug = entity.external_ids.extra.get("pornhub_model_slug", "")
    if not slug and entity.name:
        slug = entity.name.lower().replace(" ", "-").strip()

    if not slug:
        return entity

    try:
        profile = ph.fetch_model(slug)
    except Exception as exc:
        LOG.debug("pornhub: fetch_model(%r): %s", slug, exc)
        return entity

    extra = _performer_extra(slug, profile)
    merged = entity.external_ids.merge(ExternalIds(extra=extra))
    return entity.model_copy(update={"external_ids": merged})


def get_model_profile(slug: str):
    """Fetch a Pornhub model profile by slug.

    Returns a :class:`pypornhub.ModelProfile` or ``None`` on error.
    Convenience wrapper for enrichment scripts that want the raw profile.
    """
    import pypornhub as ph
    try:
        return ph.fetch_model(slug)
    except Exception as exc:
        LOG.warning("pornhub fetch_model failed for %s: %s", slug, exc)
        return None


register(PornhubProvider())
register(PornhubPersonProvider())
