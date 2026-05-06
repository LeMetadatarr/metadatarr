"""Anna's Archive metadata provider.

Anna's Archive is a file index aggregating books from shadow libraries.  It is
not an authoritative bibliographic source, so the confidence base is kept low
(0.55).  No ``enrich()`` is implemented because the md5 field is a file hash,
not a bibliographic identifier.

Keys written to :attr:`ExternalIds.extra`:

- ``annas_archive_md5``       — file content hash
- ``annas_archive_cover_url`` — cover image URL (optional)
- ``annas_archive_size``      — human-readable file size string (optional)
- ``annas_archive_formats``   — comma-joined list of available file formats
"""
from __future__ import annotations

import logging
from typing import Optional

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from mediavocab.models import ExternalIds
from mediavocab import MediaType
from mediavocab.models.signals import Signals, match_quality

LOG = logging.getLogger("metadatarr.resolve.providers.annas_archive")


class AnnasArchiveProvider(MetadataProvider):
    name = "annas_archive"
    media = {MediaType.BOOK}
    # Books are not classified by tutubo ContentType values; leave empty so
    # content_type filtering never excludes book results.
    content_types: set = set()

    def __init__(self) -> None:
        from metadatarr.client import AnnasArchiveClient
        self._client = AnnasArchiveClient()

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if signals.medium and signals.medium != MediaType.BOOK:
            return None

        try:
            results = self._client.search(signals.title)
        except Exception as exc:
            LOG.warning("annas_archive search failed: %s", exc)
            return None

        if not results:
            return None
        top = results[0]

        extra: dict = {"annas_archive_md5": top.md5}
        if top.cover_url:
            extra["annas_archive_cover_url"] = top.cover_url
        if top.size:
            extra["annas_archive_size"] = top.size
        if top.formats:
            extra["annas_archive_formats"] = ",".join(top.formats)

        cand_signals = Signals(
            title=top.title,
            artist=top.author,
            medium=MediaType.BOOK,
            language=top.language,
            content_type="book",
        )

        return ProviderMatch(
            provider=self.name,
            confidence=0.55 * match_quality(signals, cand_signals),
            signals=cand_signals,
            external_ids=ExternalIds(extra=extra),
        )


register(AnnasArchiveProvider())
