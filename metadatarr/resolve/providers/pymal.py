"""pymal provider — direct MyAnimeList scraper with ARM cross-reference bridge.

Provides four capabilities:

  1. Title search for anime and manga returning ``mal_id`` + ARM cross-references
     (``anilist_id``, ``anidb_id``, ``imdb``, ``tmdb_tv``, ``tvdb``) in one shot.

  2. ``enrich()`` by ``mal_id`` — calls ARM to fill all ID systems without
     fetching the MAL detail page (lightweight, cacheable).

  3. ``enrich_full()`` — fetches the full detail page and returns a
     ``ProviderMatch`` with every entity relation populated and MAL entity IDs
     (``mal_studio_id``, ``mal_person_id``, ``mal_character_id``) set.

  4. ``PymalPersonProvider`` and ``PymalCharacterProvider`` — enrich person/
     character records when the respective IDs are present.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from mediavocab import MediaType, PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from mediavocab.taxonomy import GENRE_ANIME, GENRE_MANGA
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity

LOG = logging.getLogger("metadatarr.resolve.providers.pymal")

_AVAILABLE: Optional[bool] = None


def _check_available() -> bool:
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            import pymal as _  # noqa: F401
            _AVAILABLE = True
        except ImportError:
            _AVAILABLE = False
    return _AVAILABLE


# ---------------------------------------------------------------------------
# ARM helper
# ---------------------------------------------------------------------------

def _arm_enrich(mal_id: int) -> ExternalIds:
    try:
        from pymal.arm import get_ids, to_external_ids
        return to_external_ids(get_ids(mal_id))
    except Exception as exc:
        LOG.warning("ARM enrich failed for mal_id=%s: %s", mal_id, exc)
        return ExternalIds()


def _arm_enrich_any(external_ids: ExternalIds) -> ExternalIds:
    """ARM lookup using whichever anime ID is available (bidirectional)."""
    try:
        from pymal.arm import enrich_external_ids, to_external_ids
        data = enrich_external_ids(external_ids)
        return to_external_ids(data) if data else ExternalIds()
    except Exception as exc:
        LOG.warning("ARM bidirectional enrich failed: %s", exc)
        return ExternalIds()


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def _anime_card_to_match(card, provider: str = "pymal_anime") -> ProviderMatch:
    arm_ids = _arm_enrich(card.mal_id)
    return ProviderMatch(
        provider=provider,
        confidence=0.80,
        signals=Signals(
            title=card.title,
            medium=MediaType.EPISODIC_SERIES,
            content_genres=[GENRE_ANIME],
        ),
        external_ids=ExternalIds(mal_id=card.mal_id).merge(arm_ids),
    )


def _manga_card_to_match(card, provider: str = "pymal_manga") -> ProviderMatch:
    arm_ids = _arm_enrich(card.mal_id)
    return ProviderMatch(
        provider=provider,
        confidence=0.80,
        signals=Signals(
            title=card.title,
            medium=MediaType.COMIC,
            content_genres=[GENRE_MANGA],
        ),
        external_ids=ExternalIds(mal_id=card.mal_id).merge(arm_ids),
    )


def _relations_from_anime(anime) -> dict:
    relations: dict = {}

    for studio_name in anime.studios:
        studio_mal_id = anime.studio_ids.get(studio_name)
        s_ids = ExternalIds(mal_studio_id=studio_mal_id) if studio_mal_id else ExternalIds()
        relations.setdefault(EntityRole.STUDIO, []).append(ProviderEntity(
            role=EntityRole.STUDIO,
            name=studio_name,
            external_ids=s_ids,
        ))

    for producer_name in anime.producers:
        prod_mal_id = anime.producer_ids.get(producer_name)
        p_ids = ExternalIds(mal_studio_id=prod_mal_id) if prod_mal_id else ExternalIds()
        relations.setdefault(EntityRole.PRODUCER, []).append(ProviderEntity(
            role=EntityRole.PRODUCER,
            name=producer_name,
            external_ids=p_ids,
        ))

    for char in anime.characters:
        char_ids = ExternalIds(mal_character_id=char.mal_id if char.mal_id else None)
        relations.setdefault(EntityRole.OTHER, []).append(ProviderEntity(
            role=EntityRole.OTHER,
            name=char.name,
            external_ids=char_ids,
        ))
        if char.voice_actor_name:
            va_ids = ExternalIds()
            if char.va_url:
                import re as _re
                m = _re.search(r"/people/(\d+)/", char.va_url)
                if m:
                    va_ids = ExternalIds(mal_person_id=int(m.group(1)))
            relations.setdefault(EntityRole.VOICE_ACTOR, []).append(ProviderEntity(
                role=EntityRole.VOICE_ACTOR,
                name=char.voice_actor_name,
                external_ids=va_ids,
            ))

    for staff in anime.staff:
        role_str = (staff.role or "").lower()
        if "director" in role_str:
            er = EntityRole.DIRECTOR
        elif "producer" in role_str:
            er = EntityRole.PRODUCER
        elif "composer" in role_str or "music" in role_str:
            er = EntityRole.COMPOSER
        elif "script" in role_str or "series composition" in role_str or "screenplay" in role_str:
            er = EntityRole.WRITER
        else:
            er = EntityRole.OTHER
        staff_ids = ExternalIds(mal_person_id=staff.mal_id if staff.mal_id else None)
        relations.setdefault(er, []).append(ProviderEntity(
            role=er,
            name=staff.name,
            external_ids=staff_ids,
        ))

    return relations


def _relations_from_manga(manga) -> dict:
    relations: dict = {}
    for author in manga.authors:
        author_ids = ExternalIds(mal_person_id=author.mal_id if author.mal_id else None)
        relations.setdefault(EntityRole.AUTHOR, []).append(ProviderEntity(
            role=EntityRole.AUTHOR,
            name=author.name,
            external_ids=author_ids,
        ))
    return relations


# ---------------------------------------------------------------------------
# Anime provider
# ---------------------------------------------------------------------------

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
# Manga provider
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Person provider
# ---------------------------------------------------------------------------

class PymalPersonProvider(MetadataProvider):
    name = "pymal_person"

    def is_available(self) -> bool:
        return _check_available()

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return None

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        if not external_ids.mal_person_id:
            return None
        try:
            import pymal as _pymal
            person = _pymal.get_person(external_ids.mal_person_id)
        except Exception as exc:
            LOG.warning("pymal_person enrich failed for mal_person_id=%s: %s",
                        external_ids.mal_person_id, exc)
            return None

        extra = dict(external_ids.extra or {})
        if person.japanese_name:
            extra.setdefault("name_japanese", person.japanese_name)
        if person.birthday:
            extra.setdefault("birthday", person.birthday)
        staff_roles_count = len(getattr(person, "staff_anime_roles", []) or [])
        if staff_roles_count:
            extra.setdefault("mal_staff_roles_count", str(staff_roles_count))

        return ExternalIds(mal_person_id=external_ids.mal_person_id, extra=extra)


# ---------------------------------------------------------------------------
# Character provider
# ---------------------------------------------------------------------------

class PymalCharacterProvider(MetadataProvider):
    name = "pymal_character"

    def is_available(self) -> bool:
        return _check_available()

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return None

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        if not external_ids.mal_character_id:
            return None
        try:
            import pymal as _pymal
            char = _pymal.get_character(external_ids.mal_character_id)
        except Exception as exc:
            LOG.warning("pymal_character enrich failed for mal_character_id=%s: %s",
                        external_ids.mal_character_id, exc)
            return None

        extra = dict(external_ids.extra or {})
        if char.japanese_name:
            extra.setdefault("name_japanese", char.japanese_name)
        if char.anime_roles:
            extra.setdefault("mal_appears_in",
                             ",".join(str(r.anime_title) for r in char.anime_roles[:5]))

        return ExternalIds(mal_character_id=external_ids.mal_character_id, extra=extra)


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


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register(PymalAnimeProvider())
register(PymalMangaProvider())
register(PymalPersonProvider())
register(PymalCharacterProvider())
