"""Prog Archives provider via :mod:`pyprogarchives` (optional dep).

Resolves a progressive-rock band to its stable progarchives id and emits an
artist (group) entity. Activates for ``PlaybackType.AUDIO`` signals tagged
``"rock"`` or ``"progressive rock"``.

Keys written to :attr:`ExternalIds.extra`:

- ``progarchives_artist`` — numeric band id (canonical)
- ``progarchives_url``    — canonical band page
"""
from __future__ import annotations

import logging
from typing import Optional

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab import PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals

LOG = logging.getLogger("metadatarr.resolve.providers.progarchives")


def _confidence(query: str, hit: str) -> float:
    q, h = query.lower().strip(), hit.lower().strip()
    if not q:
        return 0.0
    if q == h:
        return 0.95
    if q in h or h in q:
        return 0.75
    qt, ht = set(q.split()), set(h.split())
    return 0.4 + 0.3 * (len(qt & ht) / max(1, len(qt)))


class ProgArchivesProvider(MetadataProvider):
    """Resolve a progressive-rock band to its progarchives id + entity."""

    name = "progarchives"
    playback_type = {PlaybackType.AUDIO}
    genre_filter = {"rock", "progressive rock"}

    def __init__(self) -> None:
        try:
            import pyprogarchives as _lib  # noqa: WPS433
            self._lib = _lib
            self._available = True
        except ImportError:
            self._lib = None
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not self._available:
            return None
        query = (signals.artist or signals.title or "").strip()
        if not query:
            return None
        try:
            hits = self._lib.search_artists(query, limit=1)
        except Exception as exc:
            LOG.warning("progarchives search failed: %s", exc)
            return None
        if not hits:
            return None
        best = hits[0]
        entity = ProviderEntity(
            role=EntityRole.ARTIST,
            name=best.display_name,
            external_ids=ExternalIds(extra={"progarchives_artist": best.site_id}),
        )
        return ProviderMatch(
            provider=self.name,
            confidence=_confidence(query, best.display_name),
            external_ids=ExternalIds(extra=best.to_external_ids_dict()),
            relations={EntityRole.ARTIST: [entity]},
        )


register(ProgArchivesProvider())
