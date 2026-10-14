"""LibriVox provider — public-domain audiobooks.

Uses the LibriVox public REST API (no key required).
API reference: https://librivox.org/api/info
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from mediavocab import MediaType, PlaybackType
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.transport import discard_cached, make_session

LOG = logging.getLogger("metadatarr.resolve.providers.librivox")
_SESSION = make_session()

_API = "https://librivox.org/api/feed/audiobooks/"  # trailing slash required by LibriVox


_SUBTITLE = re.compile(r"\s*(?:,\s+or\s+|:\s+|\s+-\s+|;\s+)", re.IGNORECASE)


def _headline(title: str, query: str) -> str:
    """The catalogue title without its subtitle when the query asked for the short form.

    LibriVox files books under the long title ("Frankenstein, or The Modern
    Prometheus"); consolidation compares titles fuzzily and drops a match
    whose title is that much longer than the one asked for.
    """
    head = _SUBTITLE.split(title, maxsplit=1)[0]
    if head and head != title and head.casefold() == query.strip().casefold():
        return head
    return title


class LibriVoxProvider(MetadataProvider):
    """LibriVox audiobook catalogue — free, no key, public domain only."""

    name = "librivox"
    media = {MediaType.AUDIOBOOK}
    playback_type = {PlaybackType.AUDIO}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if signals.medium and signals.medium != MediaType.AUDIOBOOK:
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
            resp = None
            try:
                resp = _SESSION.get(_API, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                LOG.warning("librivox lookup failed: %s", exc)
                if resp is not None:
                    discard_cached(_SESSION, resp)
                return {}
            if not data.get("books"):
                discard_cached(_SESSION, resp)
            return data

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
                title=_headline(top.get("title") or signals.title, signals.title),
                year=year,
                language=top.get("language"),
                medium=MediaType.AUDIOBOOK,
            ),
            external_ids=ExternalIds(librivox_id=book_id),
            relations=relations,
        )


register(LibriVoxProvider())
