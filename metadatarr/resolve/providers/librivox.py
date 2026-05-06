"""LibriVox provider — public-domain audiobooks.

Uses the LibriVox public REST API (no key required).
API reference: https://librivox.org/api/info
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote_plus

from mediavocab import MediaType
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

LOG = logging.getLogger("metadatarr.resolve.providers.librivox")

_API = "https://librivox.org/api/feed/audiobooks/"  # trailing slash required by LibriVox


class LibriVoxProvider(MetadataProvider):
    """LibriVox audiobook catalogue — free, no key, public domain only."""

    name = "librivox"
    media = {MediaType.AUDIOBOOK}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if signals.medium and signals.medium != MediaType.AUDIOBOOK:
            return None
        if httpx is None:
            LOG.warning("httpx not installed — librivox provider unavailable")
            return None

        # The LibriVox API returns HTTP 500 when ``title=^X`` and
        # ``author=Y`` are passed together. Try title-only first; only
        # fall back to author-only if title alone yields nothing.
        base_params = {
            "title": f"^{signals.title}",
            "format": "json",
            "extended": "1",
            "limit": "5",
        }

        def _query(params):
            try:
                resp = httpx.get(_API, params=params, timeout=10)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                LOG.warning("librivox lookup failed: %s", exc)
                return {}

        data = _query(base_params)
        if not data.get("books") and signals.artist:
            data = _query({**{k: v for k, v in base_params.items() if k != "title"},
                            "author": signals.artist})

        books = data.get("books") or []
        if not books:
            return None

        top = books[0]
        book_id = int(top.get("id", 0)) or None

        relations: dict = {}
        authors = top.get("authors") or []
        if authors:
            entities = []
            for a in authors:
                name = f"{a.get('first_name', '')} {a.get('last_name', '')}".strip()
                if name:
                    entities.append(ProviderEntity(
        role=EntityRole.AUTHOR,
                        name=name,
                        external_ids=ExternalIds(
                            extra={"librivox_author_id": str(a["id"])} if a.get("id") else {},
                        ),
                    ))
            if entities:
                relations[EntityRole.AUTHOR] = entities

        year: Optional[int] = None
        pub = top.get("copyright_year") or top.get("catalog_date") or ""
        if pub and len(str(pub)) >= 4 and str(pub)[:4].isdigit():
            year = int(str(pub)[:4])

        return ProviderMatch(
            provider=self.name,
            confidence=0.80,
            signals=Signals(
                title=top.get("title") or signals.title,
                year=year,
                language=top.get("language"),
                medium=MediaType.AUDIOBOOK,
            ),
            external_ids=ExternalIds(librivox_id=book_id),
            relations=relations,
        )


register(LibriVoxProvider())
