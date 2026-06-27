"""FullPorner.com metadata provider — video search and performer cross-references.

fullporner.com is a free tube site focused on full-length scenes.  It carries
structured per-video data: duration, categories (tags), and performer slugs.
Confidence is capped at 0.60 — titles are user-supplied and not cross-linked
to any canonical ID space, but duration matching is a strong secondary signal.

Keys written to :attr:`ExternalIds.extra`:

Video
-----
- ``fullporner_id``        — hex video ID used in /watch/<id>
- ``fullporner_url``       — canonical watch URL
- ``fullporner_stream_url``— best signed MP4 URL (expires ~1h)
- ``fullporner_categories``— JSON array of category slug strings
- ``fullporner_duration``  — "35:36" formatted string

Performer (written on ACTOR ProviderEntity)
-------------------------------------------
- ``fullporner_slug``      — slug for /pornstar/<slug>
- ``fullporner_avatar_url``— avatar image URL
"""
from __future__ import annotations

import difflib
import json
import logging
from typing import Dict, List, Optional

from mediavocab import MediaType, PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from mediavocab.taxonomy import GENRE_ADULT
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity

LOG = logging.getLogger("metadatarr.resolve.providers.pyfullporner")

_MEDIA = {MediaType.SHORT_FILM, MediaType.MOVIE}


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _video_external_ids(meta) -> ExternalIds:
    extra: dict = {
        "fullporner_id":  meta.video_id,
        "fullporner_url": meta.url,
    }
    if meta.best_stream:
        extra["fullporner_stream_url"] = meta.best_stream.url
    if meta.categories:
        extra["fullporner_categories"] = json.dumps(meta.categories)
    if meta.duration:
        extra["fullporner_duration"] = meta.duration
    return ExternalIds(extra=extra)


def _build_actor_entities(meta) -> List[ProviderEntity]:
    entities = []
    for slug, name in zip(meta.pornstars, meta.pornstar_names):
        entities.append(ProviderEntity(
            role=EntityRole.ACTOR,
            name=name,
            external_ids=ExternalIds(extra={
                "fullporner_slug":      slug,
                "fullporner_avatar_url": f"//static.xiaoshenke.net/img/pornstars-v1/{slug}.jpg",
            }),
        ))
    return entities


class FullPornerProvider(MetadataProvider):
    """FullPorner video search and enrichment."""

    name = "fullporner"
    media = _MEDIA
    playback_type = {PlaybackType.VIDEO}
    genre_filter = {GENRE_ADULT}

    def is_available(self) -> bool:
        try:
            import pyfullporner  # noqa: F401
            return True
        except ImportError:
            return False

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if signals.medium and signals.medium not in _MEDIA:
            return None

        import pyfullporner as fp

        try:
            results = fp.search_videos(signals.title)
        except Exception as exc:
            LOG.warning("fullporner search failed: %s", exc)
            return None

        if not results:
            return None

        best = max(results, key=lambda r: _ratio(signals.title, r.title))
        ratio = _ratio(signals.title, best.title)
        if ratio < 0.45:
            return None

        try:
            meta = fp.fetch_video(best.video_id)
        except Exception as exc:
            LOG.warning("fullporner fetch_video failed for %s: %s", best.video_id, exc)
            return None

        confidence = 0.45 + 0.15 * ratio
        if signals.runtime and meta.duration_seconds:
            if abs(signals.runtime - meta.duration_seconds) < 30:
                confidence = min(confidence + 0.08, 0.60)

        actors = _build_actor_entities(meta)

        return ProviderMatch(
            provider=self.name,
            confidence=min(confidence, 0.60),
            signals=Signals(
                title=meta.title,
                runtime=float(meta.duration_seconds) if meta.duration_seconds else None,
                medium=MediaType.SHORT_FILM,
                content_genres=[GENRE_ADULT],
            ),
            external_ids=_video_external_ids(meta),
            relations={EntityRole.ACTOR: actors} if actors else {},
        )

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        vid = external_ids.extra.get("fullporner_id")
        if not vid:
            return None

        import pyfullporner as fp

        try:
            meta = fp.fetch_video(vid)
        except Exception as exc:
            LOG.warning("fullporner enrich failed for %s: %s", vid, exc)
            return None

        return external_ids.merge(_video_external_ids(meta))


def enrich_performer_entity(entity: ProviderEntity) -> ProviderEntity:
    """Fetch a FullPorner pornstar profile and merge data into entity.

    Resolution: ``extra["fullporner_slug"]`` first, then name→slug normalisation.
    Merges ``fullporner_slug`` and ``fullporner_avatar_url`` into extra.
    Physical attributes are not available on fullporner.com — use IAFD or
    FreeOnes providers for biographical data.
    """
    try:
        import pyfullporner as fp
    except ImportError:
        return entity

    slug = entity.external_ids.extra.get("fullporner_slug", "")
    if not slug and entity.name:
        slug = entity.name.lower().replace(" ", "-").strip()

    if not slug:
        return entity

    try:
        profile = fp.fetch_pornstar(slug)
    except Exception as exc:
        LOG.debug("fullporner: fetch_pornstar(%r): %s", slug, exc)
        return entity

    extra = {
        "fullporner_slug":       slug,
        "fullporner_avatar_url": profile.avatar_url,
        "fullporner_url":        profile.url,
    }
    merged = entity.external_ids.merge(ExternalIds(extra=extra))
    return entity.model_copy(update={"external_ids": merged})


register(FullPornerProvider())
