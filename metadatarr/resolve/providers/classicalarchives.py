"""Classical Archives provider via :mod:`pyclassicalarchives` (optional dep).

Resolves a classical composer to its stable Classical Archives id and emits a
composer entity. Activates for ``PlaybackType.AUDIO`` signals tagged
``"classical"``.

Keys written to :attr:`ExternalIds.extra`:

- ``classicalarchives_composer`` — numeric composer id (canonical)
- ``classicalarchives_url``      — canonical composer page
"""
from __future__ import annotations

import logging
from typing import Optional

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab import PlaybackType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals

LOG = logging.getLogger("metadatarr.resolve.providers.classicalarchives")


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


class ClassicalArchivesProvider(MetadataProvider):
    """Resolve a classical composer to Classical Archives id + entity."""

    name = "classicalarchives"
    playback_type = {PlaybackType.AUDIO}
    genre_filter = {"classical"}

    def __init__(self) -> None:
        try:
            import pyclassicalarchives as _lib  # noqa: WPS433
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
            hits = self._lib.search_composers(query, limit=1)
        except Exception as exc:
            LOG.warning("classicalarchives search failed: %s", exc)
            return None
        if not hits:
            return None
        best = hits[0]
        entity = ProviderEntity(
            role=EntityRole.COMPOSER,
            name=best.display_name,
            image_url=best.image,
            external_ids=ExternalIds(extra={"classicalarchives_composer": best.site_id}),
        )
        return ProviderMatch(
            provider=self.name,
            confidence=_confidence(query, best.display_name),
            external_ids=ExternalIds(extra=best.to_external_ids_dict()),
            relations={EntityRole.COMPOSER: [entity]},
        )


register(ClassicalArchivesProvider())
