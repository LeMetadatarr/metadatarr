"""dvdcompare.net metadata provider (HTML scraper, no API key required).

DVDCompare's speciality is explicit "Version" metadata — Director's Cut vs.
Theatrical, which region's disc carries which extras, runtime differences
between cuts.  It is the best source for version/edition disambiguation.

Keys written to :attr:`ExternalIds.extra`:

- ``dvdcompare_url``         — canonical comparison page URL
- ``dvdcompare_version``     — version string ("Director's Cut", "Theatrical", …)
- ``dvdcompare_version_diff``— raw CUTS: text blob
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Optional

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.external_ids import ExternalIds
from metadatarr.resolve.signals import Medium, Signals, VariantKind, match_quality

LOG = logging.getLogger("metadatarr.resolve.providers.dvdcompare")

_VARIANT_MAP = {
    "director": VariantKind.DIRECTORS,
    "theatrical": VariantKind.THEATRICAL,
    "extended": VariantKind.EXTENDED,
    "remaster": VariantKind.REMASTERED,
    "regional": VariantKind.REGIONAL,
}


def _infer_variant(version: Optional[str]) -> Optional[VariantKind]:
    if not version:
        return None
    v = version.lower()
    for keyword, kind in _VARIANT_MAP.items():
        if keyword in v:
            return kind
    return None


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _year_from_title(title: str) -> Optional[int]:
    """Extract the trailing (YYYY) year DVDCompare appends to titles."""
    m = re.search(r"\((\d{4})\)\s*$", title)
    return int(m.group(1)) if m else None


def _match_to_provider(signals: Signals, top) -> ProviderMatch:
    variant_kind = _infer_variant(top.version)
    cand_year    = _year_from_title(top.title or "")
    cand_signals = Signals(
        title=top.title,
        year=cand_year,
        medium=signals.medium or Medium.MOVIE,
        source_format=top.disc_format or "Blu-ray",
        region=top.region,
        variant_kind=variant_kind,
        edition=top.version,
    )
    quality = match_quality(signals, cand_signals)

    extra: dict = {}
    if top.url:
        extra["dvdcompare_url"] = top.url
    if top.version:
        extra["dvdcompare_version"] = top.version
    if top.version_differences:
        extra["dvdcompare_version_diff"] = top.version_differences

    return ProviderMatch(
        provider="dvdcompare",
        confidence=0.60 * quality,
        signals=cand_signals,
        external_ids=ExternalIds(
            imdb=top.imdb_id,
            dvdcompare_id=top.dvdcompare_id,
            extra=extra,
        ),
    )


class DVDCompareProvider(MetadataProvider):
    name = "dvdcompare"
    media = {Medium.MOVIE, Medium.TV}

    def __init__(self) -> None:
        from metadatarr.client import DVDCompareClient
        self._client = DVDCompareClient()

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None

        try:
            hits = self._client.search(signals.title)
        except Exception as exc:
            LOG.warning("dvdcompare search failed: %s", exc)
            return None

        if not hits:
            return None

        # Pick the hit whose title is closest to the query rather than
        # blindly returning the first result.
        best = max(hits, key=lambda h: _title_similarity(signals.title, h.title))
        return _match_to_provider(signals, best)

    def enrich(self, external_ids: ExternalIds,
               signals: Optional[Signals] = None) -> Optional[ProviderMatch]:
        """Fetch the full DVDCompare edition page when we already have the id."""
        fid = external_ids.dvdcompare_id
        if not fid:
            # Fall back to URL stored in extra if available
            url = (external_ids.extra or {}).get("dvdcompare_url")
            if not url:
                return None
            try:
                top = self._client.get_edition(url)  # takes a URL string
            except Exception as exc:
                LOG.warning("dvdcompare enrich by url failed: %s", exc)
                return None
        else:
            try:
                top = self._client.get_edition_by_fid(fid)
            except Exception as exc:
                LOG.warning("dvdcompare enrich by fid=%s failed: %s", fid, exc)
                return None

        if top is None:
            return None

        variant_kind = _infer_variant(top.version)
        cand_signals = Signals(
            title=top.title,
            medium=(signals.medium if signals else None) or Medium.MOVIE,
            variant_kind=variant_kind,
            edition=top.version,
        )

        extra: dict = {}
        if top.url:
            extra["dvdcompare_url"] = top.url
        if top.version:
            extra["dvdcompare_version"] = top.version
        if top.version_differences:
            extra["dvdcompare_version_diff"] = top.version_differences
        if top.cut_runtimes:
            extra["dvdcompare_cut_runtimes"] = [
                {"cut": cr.cut, "runtime_seconds": cr.runtime_seconds}
                for cr in top.cut_runtimes
            ]

        return ProviderMatch(
            provider=self.name,
            confidence=0.90,  # direct ID lookup — high confidence
            signals=cand_signals,
            external_ids=ExternalIds(
                imdb=top.imdb_id,
                dvdcompare_id=top.dvdcompare_id,
                extra=extra,
            ),
        )


register(DVDCompareProvider())
