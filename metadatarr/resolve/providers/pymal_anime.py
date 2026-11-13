"""pymal anime provider — direct MyAnimeList scraper with ARM cross-reference bridge.

Provides:

  1. Title search for anime returning ``mal_id`` + ARM cross-references
     (``anilist_id``, ``anidb_id``, ``imdb``, ``tmdb_tv``, ``tvdb``) in one shot.

  2. ``enrich()`` by ``mal_id`` — calls ARM to fill all ID systems without
     fetching the MAL detail page (lightweight, cacheable).

  3. ``enrich_full()`` — fetches the full detail page and returns a
     ``ProviderMatch`` with every entity relation populated and MAL entity IDs
     (``mal_studio_id``, ``mal_person_id``, ``mal_character_id``) set.
"""
from __future__ import annotations

from typing import List, Optional

from mediavocab import MediaType, PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from mediavocab.taxonomy import GENRE_ANIME
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.providers._pymal_common import (
    LOG,
    _anime_card_to_match,
    _arm_enrich,
    _arm_enrich_any,
    _check_available,
    _relations_from_anime,
)


class PymalAnimeProvider(MetadataProvider):
    name = "pymal_anime"
    media = {MediaType.EPISODIC_SERIES, MediaType.MOVIE}
    playback_type = {PlaybackType.VIDEO}
    genre_filter = {GENRE_ANIME}

    def is_available(self) -> bool:
        return _check_available()

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title or not self.matches(signals):
            return None
        try:
            import pymal as _pymal
            results = _pymal.search_anime(signals.title)
        except Exception as exc:
            LOG.warning("pymal_anime search failed: %s", exc)
            return None
        if not results:
            return None
        return _anime_card_to_match(results[0])

    def lookup_candidates(self, signals: Signals) -> List[ProviderMatch]:
        if not signals.title or not self.matches(signals):
            return []
        try:
            import pymal as _pymal
            results = _pymal.search_anime(signals.title)
        except Exception as exc:
            LOG.warning("pymal_anime search failed: %s", exc)
            return []
        top = sorted(results[:10], key=lambda c: c.members or 0, reverse=True)[:5]
        return [_anime_card_to_match(c) for c in top]

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        # Bidirectional: fires on mal_id, anilist_id, anidb_id, tvdb, or imdb
        arm_ids = _arm_enrich_any(external_ids)
        if not any([arm_ids.mal_id, arm_ids.anilist_id, arm_ids.anidb_id,
                    arm_ids.imdb, arm_ids.tmdb_tv, arm_ids.tvdb]):
            return None
        # arm_ids are authoritative for the ID bridge; merge with input last
        # so the caller's existing IDs win on conflict (ExternalIds.merge is
        # first-writer-wins — arm provides the base, input fills gaps it misses)
        return arm_ids.merge(external_ids)

    def enrich_full(self, mal_id: int) -> Optional[ProviderMatch]:
        try:
            import pymal as _pymal
            anime = _pymal.get_anime(mal_id)
        except Exception as exc:
            LOG.warning("pymal_anime enrich_full failed: %s", exc)
            return None

        arm_ids = _arm_enrich(mal_id)
        extra: dict = {}
        if anime.english_title:
            extra["title_english"] = anime.english_title
        if anime.japanese_title:
            extra["title_japanese"] = anime.japanese_title
        if anime.score:
            extra["mal_score"] = str(anime.score)
        if anime.genres:
            extra["mal_genres"] = ",".join(anime.genres)

        base_ids = ExternalIds(mal_id=mal_id, extra=extra).merge(arm_ids)

        return ProviderMatch(
            provider=self.name,
            confidence=0.95,
            signals=Signals(
                title=anime.title,
                year=anime.year,
                medium=MediaType.EPISODIC_SERIES if anime.type != "Movie" else MediaType.MOVIE,
                content_genres=[GENRE_ANIME],
            ),
            external_ids=base_ids,
            relations=_relations_from_anime(anime),
        )


# ---------------------------------------------------------------------------
# Standalone convenience functions
# ---------------------------------------------------------------------------

def lookup_by_mal_id(mal_id: int) -> Optional[ProviderMatch]:
    """Fetch full Anime detail + ARM cross-references, return a ProviderMatch
    that can be fed directly into metadatarr.consolidate()."""
    provider = PymalAnimeProvider()
    return provider.enrich_full(mal_id)


def lookup_by_imdb(imdb_id: str, year: Optional[int] = None) -> Optional[ProviderMatch]:
    """Look up an anime by its IMDb ID and return a full ProviderMatch.

    Chain: IMDb → TVmaze (title) → AniList (idMal) → ARM → enrich_full.
    This is the same chain used by ``pymal.get_anime_by_imdb``, but returns
    a metadatarr ``ProviderMatch`` with entity relations instead of an Anime.

    Args:
        imdb_id: IMDb ID string, e.g. ``"tt0213338"``.
        year: Optional release year hint (passed to AniList for disambiguation).

    Returns:
        A ProviderMatch (confidence 0.95) with mal_id + ARM cross-references
        + full entity relations, or None if the IMDb ID cannot be resolved.
    """
    try:
        from pymal.arm import get_ids_from_imdb
        data = get_ids_from_imdb(imdb_id)
    except Exception as exc:
        LOG.warning("lookup_by_imdb: arm.get_ids_from_imdb failed: %s", exc)
        return None

    mal_id = data.get("myanimelist")
    if not mal_id:
        LOG.warning("lookup_by_imdb: could not resolve mal_id for imdb=%s", imdb_id)
        return None

    match = PymalAnimeProvider().enrich_full(int(mal_id))
    if match and not match.external_ids.imdb:
        match = ProviderMatch(
            provider=match.provider,
            confidence=match.confidence,
            signals=match.signals,
            external_ids=ExternalIds(imdb=imdb_id).merge(match.external_ids),
            relations=match.relations,
        )
    return match


register(PymalAnimeProvider())
