"""Discogs metadata provider (official public API).

Discogs is a **music database**.  It is authoritative for:

- Physical music releases: vinyl, CD, cassette, 8-track
- Music video releases: concert film LaserDiscs/VHS/DVD, official music videos
- Soundtrack albums: film/TV scores as vinyl or CD
- Catalogue numbers, barcodes, matrix numbers, label details
- Community collector stats (have/want counts, ratings)

It has sparse-to-zero coverage of **narrative feature films** on disc.
Do not use this provider to look up Alien, Blade Runner, etc. — those have
no Discogs entries.  Use DVDCompare or Blu-ray.com for feature films.

Rate limits: 25 req/min (unauthenticated) · 60 req/min (with token).
Set ``DISCOGS_TOKEN`` environment variable or pass *token* to the provider
constructor for the higher limit.

Supported media types: MUSIC, MUSIC_VIDEO, OTHER.

Keys written to :attr:`ExternalIds.extra`:

- ``discogs_url``     — Discogs release page URL
- ``discogs_label``   — label name(s), comma-separated
- ``discogs_catno``   — catalogue number
- ``discogs_cover``   — primary cover image URL
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.external_ids import ExternalIds
from metadatarr.resolve.signals import Medium, Signals, match_quality

LOG = logging.getLogger("metadatarr.resolve.providers.discogs")

# Discogs format strings that correspond to physical video media.
_VIDEO_FORMATS = ("Blu-ray", "DVD", "VHS", "Laserdisc", "HD DVD", "UHD Blu-ray")


class DiscogsProvider(MetadataProvider):
    name = "discogs"
    media = {Medium.MUSIC_VIDEO, Medium.MUSIC, Medium.OTHER}

    def __init__(self, token: Optional[str] = None) -> None:
        from metadatarr.client import DiscogsClient
        self._client = DiscogsClient(token=token)

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None

        hits = []
        try:
            if signals.medium == Medium.MUSIC_VIDEO or signals.source_format in _VIDEO_FORMATS:
                # Concert film / music video: search video formats
                fmt = signals.source_format if signals.source_format in _VIDEO_FORMATS else "Laserdisc"
                hits = self._client.search_video(signals.title, fmt=fmt)
            else:
                # MUSIC or OTHER: search audio formats
                fmt = signals.source_format or "Vinyl"
                hits = self._client.search(signals.title, fmt=fmt)
        except Exception as exc:
            LOG.warning("discogs search failed: %s", exc)

        if not hits:
            return None

        # Filter by year if provided.
        if signals.year is not None:
            year_hits = [h for h in hits if h.year and abs(h.year - signals.year) <= 1]
            if year_hits:
                hits = year_hits

        top = hits[0]
        resolved_fmt = top.format[0] if top.format else (signals.source_format or "")
        cand_signals = Signals(
            title=top.title,
            year=top.year,
            country=top.country,
            medium=signals.medium or Medium.MUSIC,
            source_format=resolved_fmt,
        )
        quality = match_quality(signals, cand_signals)

        extra: dict = {}
        if top.url:
            extra["discogs_url"] = top.url
        if top.cover_image:
            extra["discogs_cover"] = top.cover_image
        if top.label:
            extra["discogs_label"] = ", ".join(top.label)
        if top.catno:
            extra["discogs_catno"] = top.catno

        return ProviderMatch(
            provider=self.name,
            confidence=0.70 * quality,
            signals=cand_signals,
            external_ids=ExternalIds(
                discogs_release=top.id,
                extra=extra,
            ),
        )

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Fetch full release detail when a Discogs release id is already known."""
        if not external_ids.discogs_release:
            return None
        try:
            release = self._client.get_release(external_ids.discogs_release)
        except Exception:
            return None
        if release is None:
            return None

        out = ExternalIds()
        extra: dict = {}
        labels = release.label_names
        if labels:
            extra["discogs_label"] = ", ".join(labels)
        cover = release.primary_image_url
        if cover:
            extra["discogs_cover"] = cover
        if release.uri:
            extra["discogs_url"] = f"https://www.discogs.com{release.uri}" if release.uri.startswith("/") else release.uri
        out.extra = extra
        return out


register(DiscogsProvider())
