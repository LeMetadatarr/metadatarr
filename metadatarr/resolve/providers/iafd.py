"""IAFD (Internet Adult Film Database) provider — public scraper, no API key."""
from __future__ import annotations

import logging
from typing import Optional

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from mediavocab.models import ExternalIds
from mediavocab import PlaybackType
from mediavocab.models.signals import Signals

LOG = logging.getLogger("metadatarr.resolve.providers.iafd")


class IAFDProvider(MetadataProvider):
    name = "iafd"
    playback_type = {PlaybackType.VIDEO}
    genre_filter = {"adult", "porn", "xxx"}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        try:
            from pyiafd.search import search_titles
            results = search_titles(signals.title)
        except Exception as exc:
            LOG.debug("IAFD search failed: %s", exc)
            return None

        if not results:
            return None

        query = signals.title.lower()
        best_result = None
        best_confidence = -1.0

        for result in results:
            name_lower = result.name.lower()
            # Parse year from result (stored as str)
            try:
                result_year = int(result.year) if result.year else None
            except (ValueError, TypeError):
                result_year = None

            year_matches = (
                signals.year is not None
                and result_year is not None
                and abs(signals.year - result_year) <= 1
            )

            if name_lower == query and year_matches:
                confidence = 0.95
            elif name_lower == query and signals.year is None:
                confidence = 0.85
            elif query in name_lower or name_lower in query:
                confidence = 0.60
            else:
                confidence = 0.35

            if confidence > best_confidence:
                best_confidence = confidence
                best_result = result

        if best_result is None:
            best_result = results[0]
            best_confidence = 0.35

        return ProviderMatch(
            provider=self.name,
            confidence=best_confidence,
            external_ids=ExternalIds(extra={
                "iafd_title_id": best_result.id,
                "iafd_title_url": best_result.url,
            }),
        )


register(IAFDProvider())
