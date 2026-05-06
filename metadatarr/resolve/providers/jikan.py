"""Jikan provider — anime and manga via the unofficial MyAnimeList REST proxy.

No API key required. Jikan mirrors MAL data.
API reference: https://docs.api.jikan.moe/
Rate limit: 3 requests/second, 60/minute.
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

LOG = logging.getLogger("metadatarr.resolve.providers.jikan")

_BASE = "https://api.jikan.moe/v4"


def _best_title(entry: dict) -> str:
    return (entry.get("title_english")
            or entry.get("title")
            or "")


def _year(entry: dict) -> Optional[int]:
    aired = entry.get("aired") or entry.get("published") or {}
    prop = aired.get("prop") or {}
    return (prop.get("from") or {}).get("year") or entry.get("year")


class JikanAnimeProvider(MetadataProvider):
    """Jikan (MAL) — anime catalogue, no credentials."""

    name = "jikan_anime"
    media = {MediaType.EPISODIC_SERIES, MediaType.MOVIE}
    genre_filter = {"anime"}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if not self.matches(signals):
            return None
        if httpx is None:
            LOG.warning("httpx not installed — jikan_anime provider unavailable")
            return None

        try:
            resp = httpx.get(
                f"{_BASE}/anime",
                params={"q": signals.title, "limit": 5},
                timeout=10,
            )
            resp.raise_for_status()
            items = resp.json().get("data") or []
        except Exception as exc:
            LOG.warning("jikan_anime lookup failed: %s", exc)
            return None

        if not items:
            return None

        # Year-filter when we have a hint
        if signals.year is not None:
            hits = [i for i in items if _year(i) and abs(_year(i) - signals.year) <= 1]
            if hits:
                items = hits

        top = items[0]
        mal_id = top.get("mal_id")
        title = _best_title(top)
        year = _year(top)

        relations: dict = {}
        studios = top.get("studios") or []
        if studios:
            s = studios[0]
            relations[EntityRole.STUDIO] = [ProviderEntity(
        role=EntityRole.STUDIO,
                name=s.get("name", ""),
                external_ids=ExternalIds(
                    mal_studio_id=int(s["mal_id"]) if s.get("mal_id") else None,
                ),
            )]

        extra: dict = {}
        jp = top.get("title_japanese")
        if jp:
            extra["title_japanese"] = jp

        return ProviderMatch(
            provider=self.name,
            confidence=0.85,
            signals=Signals(title=title, year=year, medium=MediaType.EPISODIC_SERIES, content_genres=["anime"]),
            external_ids=ExternalIds(mal_id=mal_id, extra=extra),
            relations=relations,
        )


class JikanMangaProvider(MetadataProvider):
    """Jikan (MAL) — manga catalogue, no credentials."""

    name = "jikan_manga"
    media = {MediaType.COMIC}
    genre_filter = {"manga"}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if not self.matches(signals):
            return None
        if httpx is None:
            LOG.warning("httpx not installed — jikan_manga provider unavailable")
            return None

        try:
            resp = httpx.get(
                f"{_BASE}/manga",
                params={"q": signals.title, "limit": 5},
                timeout=10,
            )
            resp.raise_for_status()
            items = resp.json().get("data") or []
        except Exception as exc:
            LOG.warning("jikan_manga lookup failed: %s", exc)
            return None

        if not items:
            return None

        if signals.year is not None:
            hits = [i for i in items if _year(i) and abs(_year(i) - signals.year) <= 1]
            if hits:
                items = hits

        top = items[0]
        mal_id = top.get("mal_id")
        title = _best_title(top)
        year = _year(top)

        relations: dict = {}
        authors = top.get("authors") or []
        if authors:
            entries = []
            for a in authors:
                name = a.get("name", "")
                # MAL stores as "Last, First" — flip it
                if "," in name:
                    parts = [p.strip() for p in name.split(",", 1)]
                    name = f"{parts[1]} {parts[0]}"
                entries.append(ProviderEntity(
        role=EntityRole.AUTHOR,
                    name=name,
                    external_ids=ExternalIds(
                        mal_person_id=int(a["mal_id"]) if a.get("mal_id") else None,
                    ),
                ))
            relations[EntityRole.AUTHOR] = entries

        extra: dict = {}
        jp = top.get("title_japanese")
        if jp:
            extra["title_japanese"] = jp

        return ProviderMatch(
            provider=self.name,
            confidence=0.85,
            signals=Signals(title=title, year=year, medium=MediaType.COMIC, content_genres=["manga"]),
            external_ids=ExternalIds(mal_id=mal_id, extra=extra),
            relations=relations,
        )


register(JikanAnimeProvider())
register(JikanMangaProvider())
