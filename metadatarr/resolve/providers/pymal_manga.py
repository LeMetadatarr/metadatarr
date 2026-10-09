"""pymal manga provider — direct MyAnimeList scraper with ARM cross-reference bridge.

Provides title search for manga returning ``mal_id`` + ARM cross-references,
and ``enrich_full()`` fetching the full detail page with entity relations
populated (``mal_person_id`` for authors).
"""
from __future__ import annotations

from typing import List, Optional

from mediavocab import MediaType, PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from mediavocab.taxonomy import GENRE_MANGA
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.providers._pymal_common import (
    LOG,
    _arm_enrich,
    _arm_enrich_any,
    _check_available,
    _manga_card_to_match,
    _relations_from_manga,
)


class PymalMangaProvider(MetadataProvider):
    name = "pymal_manga"
    media = {MediaType.COMIC}
    playback_type = {PlaybackType.PAGED}
    genre_filter = {GENRE_MANGA}

    def is_available(self) -> bool:
        return _check_available()

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title or not self.matches(signals):
            return None
        try:
            import pymal as _pymal
            results = _pymal.search_manga(signals.title)
        except Exception as exc:
            LOG.warning("pymal_manga search failed: %s", exc)
            return None
        if not results:
            return None
        return _manga_card_to_match(results[0])

    def lookup_candidates(self, signals: Signals) -> List[ProviderMatch]:
        if not signals.title or not self.matches(signals):
            return []
        try:
            import pymal as _pymal
            results = _pymal.search_manga(signals.title)
        except Exception as exc:
            LOG.warning("pymal_manga search failed: %s", exc)
            return []
        top = sorted(results[:10], key=lambda c: c.members or 0, reverse=True)[:5]
        return [_manga_card_to_match(c) for c in top]

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        arm_ids = _arm_enrich_any(external_ids)
        if not any([arm_ids.mal_id, arm_ids.anilist_id, arm_ids.anidb_id,
                    arm_ids.imdb, arm_ids.tmdb_tv, arm_ids.tvdb]):
            return None
        return arm_ids.merge(external_ids)

    def enrich_full(self, mal_id: int) -> Optional[ProviderMatch]:
        try:
            import pymal as _pymal
            manga = _pymal.get_manga(mal_id)
        except Exception as exc:
            LOG.warning("pymal_manga enrich_full failed: %s", exc)
            return None

        arm_ids = _arm_enrich(mal_id)
        extra: dict = {}
        if manga.english_title:
            extra["title_english"] = manga.english_title
        if manga.japanese_title:
            extra["title_japanese"] = manga.japanese_title

        base_ids = ExternalIds(mal_id=mal_id, extra=extra).merge(arm_ids)

        return ProviderMatch(
            provider=self.name,
            confidence=0.95,
            signals=Signals(
                title=manga.title,
                medium=MediaType.COMIC,
                content_genres=[GENRE_MANGA],
            ),
            external_ids=base_ids,
            relations=_relations_from_manga(manga),
        )


register(PymalMangaProvider())
