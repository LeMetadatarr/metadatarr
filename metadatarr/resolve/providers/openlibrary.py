"""Open Library metadata provider (free, no auth required).

Open Library is an open, editable library catalogue run by the Internet Archive.
It provides stable work and edition IDs (OLIDs) plus ISBN cross-references.

Keys written to :attr:`ExternalIds.extra`:

- ``openlibrary_url``      — canonical work URL (https://openlibrary.org/works/OL…)
- ``openlibrary_cover_id`` — cover image numeric id (optional)
"""
from __future__ import annotations

import logging
from typing import Optional

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from mediavocab.models import ExternalIds
from mediavocab import MediaType
from mediavocab.models.signals import Signals, match_quality

LOG = logging.getLogger("metadatarr.resolve.providers.openlibrary")


class OpenLibraryProvider(MetadataProvider):
    name = "openlibrary"
    media = {MediaType.BOOK}
    # Books are not classified by tutubo ContentType values; leave empty so
    # content_type filtering never excludes book results.
    content_types: set = set()

    def __init__(self) -> None:
        from metadatarr.client import OpenLibraryClient
        self._client = OpenLibraryClient()

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
            LOG.warning("openlibrary search failed: %s", exc)
            return None

        if not results:
            return None
        top = results[0]

        author: Optional[str] = None
        if top.author_names:
            author = top.author_names[0]

        language: Optional[str] = None
        if top.language:
            language = top.language[0].lower()

        # Extract OLID from work_key — strip "/works/" prefix.
        olid: Optional[str] = None
        if top.work_key:
            olid = top.work_key.lstrip("/works/")
            if olid.startswith("OL") or olid != top.work_key:
                pass  # already stripped correctly
            # Normalise: "/works/OL27482W" → "OL27482W"
            olid = top.work_key.replace("/works/", "")

        extra: dict = {}
        if top.work_key:
            extra["openlibrary_url"] = f"https://openlibrary.org{top.work_key}"
        if top.cover_id is not None:
            extra["openlibrary_cover_id"] = str(top.cover_id)

        cand_signals = Signals(
            title=top.title,
            artist=author,
            year=top.first_publish_year,
            medium=MediaType.BOOK,
            language=language,
        )

        return ProviderMatch(
            provider=self.name,
            confidence=0.70 * match_quality(signals, cand_signals),
            signals=cand_signals,
            external_ids=ExternalIds(
                olid=olid,
                extra=extra,
            ),
        )

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Resolve edition metadata from ISBN-10 or ISBN-13.

        Triggers when ``isbn_10`` or ``isbn_13`` is set on *external_ids*.
        Returns an :class:`ExternalIds` populated with ``olid``, ``isbn_10``,
        and ``isbn_13`` from the matched edition record.
        """
        isbn: Optional[str] = external_ids.isbn_10 or external_ids.isbn_13
        if not isbn:
            return None

        try:
            edition = self._client.get_edition_by_isbn(isbn)
        except Exception as exc:
            LOG.warning("openlibrary get_edition_by_isbn failed: %s", exc)
            return None

        if edition is None:
            return None

        out = ExternalIds()
        if edition.olid:
            out.olid = edition.olid
        if edition.isbn_10:
            out.isbn_10 = edition.isbn_10[0]
        if edition.isbn_13:
            out.isbn_13 = edition.isbn_13[0]
        return out


register(OpenLibraryProvider())
