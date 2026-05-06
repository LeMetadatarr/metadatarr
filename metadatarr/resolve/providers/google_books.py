"""Google Books provider — book metadata and ISBN resolution.

No API key required for basic (unauthenticated) searches.
Quota: 1,000 requests/day without a key; 1M/day with a key.
API reference: https://developers.google.com/books/docs/v1/using
"""
from __future__ import annotations

import logging
from typing import Optional

from mediavocab import MediaType
from metadatarr.resolve.entities import EntityKind, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

LOG = logging.getLogger("metadatarr.resolve.providers.google_books")

_BASE = "https://www.googleapis.com/books/v1/volumes"


def _parse_year(date_str: str) -> Optional[int]:
    if date_str and len(date_str) >= 4 and date_str[:4].isdigit():
        return int(date_str[:4])
    return None


class GoogleBooksProvider(MetadataProvider):
    """Google Books — book and audiobook ISBN resolution, no key required."""

    name = "google_books"
    media = {MediaType.BOOK, MediaType.AUDIOBOOK}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if signals.medium and signals.medium not in {MediaType.BOOK, MediaType.AUDIOBOOK}:
            return None
        if httpx is None:
            LOG.warning("httpx not installed — google_books provider unavailable")
            return None

        # Build query: title + optional author
        q = f"intitle:{signals.title}"
        if signals.artist:
            q += f"+inauthor:{signals.artist}"

        try:
            resp = httpx.get(_BASE, params={"q": q, "maxResults": 5}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            LOG.warning("google_books lookup failed: %s", exc)
            return None

        items = data.get("items") or []
        if not items:
            return None

        # Year-filter when we have a hint
        if signals.year is not None:
            hits = [i for i in items
                    if _parse_year(i.get("volumeInfo", {}).get("publishedDate", ""))
                    and abs(_parse_year(i["volumeInfo"]["publishedDate"]) - signals.year) <= 1]
            if hits:
                items = hits

        top = items[0]
        volume_id = top.get("id")
        info = top.get("volumeInfo") or {}
        title = info.get("title") or signals.title
        year = _parse_year(info.get("publishedDate", ""))
        language = info.get("language")
        medium = signals.medium or MediaType.BOOK

        # ISBN extraction
        isbn_10: Optional[str] = None
        isbn_13: Optional[str] = None
        for iid in info.get("industryIdentifiers") or []:
            t = iid.get("type", "")
            v = iid.get("identifier", "")
            if t == "ISBN_13" and not isbn_13:
                isbn_13 = v
            elif t == "ISBN_10" and not isbn_10:
                isbn_10 = v

        # Author relations
        relations: dict = {}
        authors = info.get("authors") or []
        if authors:
            relations[EntityKind.AUTHOR] = [
                ProviderEntity(kind=EntityKind.AUTHOR, name=name)
                for name in authors
            ]

        return ProviderMatch(
            provider=self.name,
            confidence=0.80,
            signals=Signals(title=title, year=year, language=language, medium=medium),
            external_ids=ExternalIds(
                google_books_id=volume_id,
                isbn_13=isbn_13,
                isbn_10=isbn_10,
            ),
            relations=relations,
        )


register(GoogleBooksProvider())
