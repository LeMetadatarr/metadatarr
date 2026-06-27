"""TVmaze metadata provider (free, no auth required).

TVmaze is an authoritative TV database with stable numeric show IDs and
cross-references to TheTVDB and IMDb.  The free API requires no key.

Keys written to :attr:`ExternalIds.extra`:

- ``tvmaze_id``   — stable numeric show id
- ``tvmaze_url``  — canonical show URL
"""
from __future__ import annotations

import logging
from typing import Optional

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from mediavocab.models import ExternalIds
from mediavocab import MediaType, PlaybackType
from mediavocab.models.signals import Signals, match_quality

LOG = logging.getLogger("metadatarr.resolve.providers.tvmaze")


class TVmazeProvider(MetadataProvider):
    name = "tvmaze"
    media = {MediaType.EPISODIC_SERIES}
    playback_type = {PlaybackType.VIDEO}

    def __init__(self) -> None:
        from metadatarr.client import TVmazeClient
        self._client = TVmazeClient()

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if signals.medium and signals.medium != MediaType.EPISODIC_SERIES:
            return None

        try:
            results = self._client.search_shows(signals.title)
        except Exception as exc:
            LOG.warning("tvmaze search failed: %s", exc)
            return None

        if not results:
            return None
        top = results[0]

        ext = top.externals or type("_", (), {"thetvdb": None, "imdb": None, "tvrage": None})()

        extra: dict = {"tvmaze_id": str(top.id)}
        if top.url:
            extra["tvmaze_url"] = top.url

        year: Optional[int] = None
        if top.premiered:
            try:
                year = int(top.premiered[:4])
            except (ValueError, TypeError):
                pass

        runtime = float(top.runtime) if top.runtime else None

        relations: dict = {}
        # Emit each cast member as an ACTOR relation when the show lookup
        # was specific enough (single-title, not a broad search).
        # We skip cast fetching here — too many extra round-trips for a
        # provider lookup; consumers can call TVmazeClient.get_cast() directly.

        cand_signals = Signals(
            title=top.name,
            year=year,
            runtime=runtime,
            medium=MediaType.EPISODIC_SERIES,
            language=top.language,
        )
        return ProviderMatch(
            provider=self.name,
            confidence=0.7 * match_quality(signals, cand_signals),
            signals=cand_signals,
            external_ids=ExternalIds(
                imdb=ext.imdb if hasattr(ext, "imdb") else None,
                tvdb=ext.thetvdb if hasattr(ext, "thetvdb") else None,
                extra=extra,
            ),
            relations=relations,
        )


    # ------------------------------------------------------------------
    # ID-keyed enrichment — TVDB / IMDb → TVmaze + sibling cross-refs
    # ------------------------------------------------------------------

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Resolve a TVmaze record from a TVDB or IMDb id and surface the
        sibling cross-references TVmaze publishes.

        Triggers:

        - ``tvdb`` → ``TVmazeClient.lookup_by_thetvdb``
        - ``imdb`` → ``TVmazeClient.lookup_by_imdb``

        The resulting :class:`ExternalIds` adds the TVmaze numeric show id
        + URL (in ``extra``) plus whichever of ``tvdb`` / ``imdb`` the
        caller didn't already have.
        """
        show = None
        if external_ids.tvdb:
            try:
                show = self._client.lookup_by_thetvdb(int(external_ids.tvdb))
            except Exception:
                show = None
        if show is None and external_ids.imdb:
            try:
                show = self._client.lookup_by_imdb(external_ids.imdb)
            except Exception:
                show = None
        if show is None:
            return None

        out = ExternalIds()
        ext = show.externals
        if ext is not None:
            if getattr(ext, "imdb", None):
                out.imdb = ext.imdb
            if getattr(ext, "thetvdb", None):
                out.tvdb = int(ext.thetvdb)

        extra: dict = {"tvmaze_id": str(show.id)}
        if show.url:
            extra["tvmaze_url"] = show.url
        out.extra = extra
        return out


register(TVmazeProvider())
