"""AniList provider — anime and manga via the AniList GraphQL API.

No API key required. Rate limit: 90 requests/minute.
API reference: https://anilist.gitbook.io/anilist-apiv2-docs/
"""
from __future__ import annotations

import logging
from typing import Optional

from mediavocab import MediaType
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

LOG = logging.getLogger("metadatarr.resolve.providers.anilist")

_URL = "https://graphql.anilist.co"

_QUERY = """
query($search: String, $type: MediaType) {
  Media(search: $search, type: $type, sort: SEARCH_MATCH) {
    id
    title { romaji english native }
    startDate { year }
    endDate { year }
    episodes chapters volumes
    status format genres
    staff(sort: RELEVANCE, perPage: 10) {
      edges { role node { id name { full } } }
    }
    studios(isMain: true) { nodes { id name } }
  }
}
"""

# AniList staff roles → EntityKind
_ROLE_MAP = {
    "director": EntityRole.DIRECTOR,
    "original creator": EntityRole.AUTHOR,
    "original story": EntityRole.AUTHOR,
    "story": EntityRole.AUTHOR,
    "art": EntityRole.OTHER,
    "character design": EntityRole.OTHER,
    "music": EntityRole.COMPOSER,
    "series composition": EntityRole.WRITER,
    "script": EntityRole.WRITER,
}


def _map_role(role_str: str) -> Optional[EntityRole]:
    return _ROLE_MAP.get(role_str.lower().strip())


class AniListProvider(MetadataProvider):
    """AniList — anime and manga, GraphQL, no credentials.

    Routes on (media_type, content_genres). Anime requires
    ``EPISODIC_SERIES`` or ``MOVIE`` plus ``"anime"`` in
    ``content_genres``; manga requires ``COMIC`` + ``"manga"``.
    """

    name = "anilist"
    media = {MediaType.EPISODIC_SERIES, MediaType.MOVIE, MediaType.COMIC}
    genre_filter = {"anime", "manga"}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if not self.matches(signals):
            return None
        if httpx is None:
            LOG.warning("httpx not installed — anilist provider unavailable")
            return None

        is_manga = (
            signals.medium == MediaType.COMIC
            or "manga" in (signals.content_genres or [])
        )
        media_type = "MANGA" if is_manga else "ANIME"

        try:
            resp = httpx.post(
                _URL,
                json={"query": _QUERY, "variables": {"search": signals.title, "type": media_type}},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            LOG.warning("anilist lookup failed: %s", exc)
            return None

        media = (data.get("data") or {}).get("Media")
        if not media:
            return None

        anilist_id = media.get("id")
        title_obj = media.get("title") or {}
        title = title_obj.get("english") or title_obj.get("romaji") or signals.title
        year = (media.get("startDate") or {}).get("year")
        # Map back to canonical mediavocab MediaType + genre tag.
        if media_type == "MANGA":
            medium, genres = MediaType.COMIC, ["manga"]
        else:
            medium, genres = MediaType.EPISODIC_SERIES, ["anime"]

        relations: dict = {}

        # Staff → entity relations
        for edge in (media.get("staff") or {}).get("edges") or []:
            role_str = edge.get("role", "")
            role = _map_role(role_str)
            if role is None:
                continue
            node = edge.get("node") or {}
            name = (node.get("name") or {}).get("full")
            if not name:
                continue
            staff_id = node.get("id")
            entity = ProviderEntity(
                role=role,
                name=name,
                external_ids=ExternalIds(
                    anilist_staff_id=int(staff_id) if staff_id else None,
                ),
            )
            relations.setdefault(role, []).append(entity)

        # Main studio → STUDIO entity
        studios = (media.get("studios") or {}).get("nodes") or []
        if studios:
            s = studios[0]
            studio_entity = ProviderEntity(
        role=EntityRole.STUDIO,
                name=s["name"],
                external_ids=ExternalIds(
                    anilist_studio_id=int(s["id"]) if s.get("id") else None,
                ),
            )
            relations[EntityRole.STUDIO] = [studio_entity]

        extra: dict = {}
        romaji = title_obj.get("romaji")
        native = title_obj.get("native")
        if romaji and romaji != title:
            extra["title_romaji"] = romaji
        if native:
            extra["title_native"] = native

        return ProviderMatch(
            provider=self.name,
            confidence=0.90,
            signals=Signals(title=title, year=year, medium=medium, content_genres=genres),
            external_ids=ExternalIds(anilist_id=anilist_id, extra=extra),
            relations=relations,
        )


register(AniListProvider())
