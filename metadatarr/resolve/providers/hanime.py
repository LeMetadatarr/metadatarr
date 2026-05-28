"""hanime.tv metadata provider — hentai-anime video search + studio relations.

No authentication required. Gated to adult-anime queries via ``genre_filter``:
the provider is only consulted when the caller tags a lookup with the ``adult``
or ``anime`` content genre, so it never pollutes mainstream movie/TV lookups.

hanime.tv exposes stable **numeric** identifiers, which are safe canonical
cross-references. Keys written to :attr:`ExternalIds.extra`:

- ``hanime_video_id``     — numeric video id (the work)
- ``hanime_brand_id``     — numeric studio id
- ``hanime_franchise_id`` — numeric series id
- ``hanime_slug`` / ``hanime_url`` — link-back only (slug is renameable)

The studio is emitted as an :class:`EntityRole.STUDIO` relation anchored on
``hanime_brand_id``, so videos from the same studio collapse to one entity.

Confidence is capped at 0.75: titles are decent and IDs are stable, but there
is no shared ID space with MAL/AniList to anchor a higher score.
"""
from __future__ import annotations

import difflib
import logging
from typing import List, Optional

from mediavocab import MediaType, PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from mediavocab.taxonomy.genre import GENRE_ADULT, GENRE_ANIME

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity

LOG = logging.getLogger("metadatarr.resolve.providers.hanime")

_MEDIA = {MediaType.MOVIE, MediaType.EPISODIC_SERIES}
_MAX_CANDIDATES = 5


def _title_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _confidence(ratio: float) -> float:
    # 0.5 floor for a weak match, +0.25 for a near-exact title; hard cap 0.75.
    return min(0.5 + 0.25 * (ratio >= 0.9), 0.75)


def _match_from_video(video, ratio: float) -> ProviderMatch:
    from pyhanime.mediavocab import external_ids, studio_external_ids

    relations = {}
    if getattr(video, "brand", "") and getattr(video, "brand_id", ""):
        relations[EntityRole.STUDIO] = [
            ProviderEntity(
                role=EntityRole.STUDIO,
                name=video.brand,
                external_ids=ExternalIds(extra=studio_external_ids(video)),
            )
        ]

    runtime = None
    dur = getattr(video, "duration_in_ms", 0)
    if dur:
        runtime = dur / 1000.0

    return ProviderMatch(
        provider="hanime",
        confidence=_confidence(ratio),
        signals=Signals(
            title=video.name,
            artist=getattr(video, "brand", "") or None,
            runtime=runtime,
            medium=MediaType.MOVIE,
            content_genres=[GENRE_ADULT, GENRE_ANIME],
        ),
        external_ids=ExternalIds(extra=external_ids(video)),
        relations=relations,
    )


def _match_from_preview(preview, ratio: float) -> ProviderMatch:
    from pyhanime.mediavocab import external_ids, studio_external_ids

    relations = {}
    if getattr(preview, "brand", "") and getattr(preview, "brand_id", ""):
        relations[EntityRole.STUDIO] = [
            ProviderEntity(
                role=EntityRole.STUDIO,
                name=preview.brand,
                external_ids=ExternalIds(extra=studio_external_ids(preview)),
            )
        ]

    return ProviderMatch(
        provider="hanime",
        confidence=_confidence(ratio),
        signals=Signals(
            title=preview.name,
            artist=getattr(preview, "brand", "") or None,
            medium=MediaType.MOVIE,
            content_genres=[GENRE_ADULT, GENRE_ANIME],
        ),
        external_ids=ExternalIds(extra=external_ids(preview)),
        relations=relations,
    )


class HanimeProvider(MetadataProvider):
    name = "hanime"
    media = _MEDIA
    playback_type = {PlaybackType.VIDEO}
    genre_filter = {GENRE_ADULT, GENRE_ANIME}

    def is_available(self) -> bool:
        try:
            import pyhanime  # noqa: F401
            return True
        except ImportError:
            return False

    def _search(self, signals: Signals):
        if not signals.title:
            return []
        if signals.medium and signals.medium not in _MEDIA:
            return []
        import pyhanime
        try:
            return list(pyhanime.search(signals.title))
        except Exception as exc:  # network / parsing errors
            LOG.warning("hanime search failed for %r: %s", signals.title, exc)
            return []

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        previews = self._search(signals)
        if not previews:
            return None
        best = max(previews, key=lambda p: _title_ratio(signals.title, p.name))
        ratio = _title_ratio(signals.title, best.name)
        if ratio < 0.5:
            return None
        return _match_from_preview(best, ratio)

    def lookup_candidates(self, signals: Signals) -> List[ProviderMatch]:
        previews = self._search(signals)
        if not previews:
            return []
        ranked = sorted(
            previews,
            key=lambda p: _title_ratio(signals.title, p.name),
            reverse=True,
        )
        out: List[ProviderMatch] = []
        for preview in ranked[:_MAX_CANDIDATES]:
            ratio = _title_ratio(signals.title, preview.name)
            if ratio < 0.5:
                break
            out.append(_match_from_preview(preview, ratio))
        return out

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        slug = external_ids.extra.get("hanime_slug")
        if not slug:
            return None
        import pyhanime
        try:
            video = pyhanime.get_video(slug)
        except Exception as exc:
            LOG.warning("hanime enrich failed for slug %s: %s", slug, exc)
            return None
        from pyhanime.mediavocab import external_ids as build_ids
        return ExternalIds(extra=build_ids(video))


register(HanimeProvider())
