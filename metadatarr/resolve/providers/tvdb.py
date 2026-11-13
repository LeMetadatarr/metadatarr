"""TheTVDB v4 provider — requires ``TVDB_API_KEY`` env var.

Keys written to :attr:`ExternalIds.extra`:

- ``tvdb_id``   — numeric TVDB series id
- ``tvdb_slug`` — URL-friendly show slug
- ``tvdb_url``  — canonical series URL on thetvdb.com
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from unblock_requests import CloudflareSession

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from mediavocab.models import ExternalIds
from mediavocab import MediaType, PlaybackType
from mediavocab.models.signals import Signals

LOG = logging.getLogger("metadatarr.resolve.providers.tvdb")
_BASE = "https://api4.thetvdb.com/v4"

_token: Optional[str] = None
_session: Optional[CloudflareSession] = None


def _http() -> CloudflareSession:
    """Shared anti-bot HTTP transport (curl_cffi impersonation by default)."""
    global _session
    if _session is None:
        _session = CloudflareSession()
    return _session


def _authenticate() -> Optional[str]:
    global _token
    key = os.environ.get("TVDB_API_KEY", "")
    if not key:
        return None
    try:
        resp = _http().post(f"{_BASE}/login", json={"apikey": key}, timeout=20)
        resp.raise_for_status()
        _token = resp.json()["data"]["token"]
        return _token
    except Exception as exc:
        LOG.warning("TVDB authentication failed: %s", exc)
        _token = None
        return None


class TVDBProvider(MetadataProvider):
    name = "tvdb"
    # TheTVDB is the TV authority; route on the canonical TV media types
    # (axiom 13) rather than ad-hoc "tv"/"series" genre strings, which are
    # not genres and would never appear in a caller's content_genres.
    media = {MediaType.TV, MediaType.EPISODIC_SERIES}
    playback_type = {PlaybackType.VIDEO}

    def is_available(self) -> bool:
        return bool(os.environ.get("TVDB_API_KEY", ""))

    def _get_token(self) -> Optional[str]:
        global _token
        if _token:
            return _token
        return _authenticate()

    def _search(self, title: str, *, retry: bool = True) -> Optional[list]:
        token = self._get_token()
        if not token:
            return None
        try:
            resp = _http().get(
                f"{_BASE}/search",
                params={"query": title, "type": "series"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )
            if resp.status_code == 401 and retry:
                _authenticate()
                return self._search(title, retry=False)
            resp.raise_for_status()
            return resp.json().get("data") or []
        except Exception as exc:
            LOG.warning("TVDB search failed: %s", exc)
            return None

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        try:
            results = self._search(signals.title)
        except Exception as exc:
            LOG.warning("TVDB lookup error: %s", exc)
            return None

        if not results:
            return None

        query = signals.title.lower()
        best = None
        best_confidence = -1.0

        for result in results:
            name = (result.get("name") or "").lower()
            result_year: Optional[int] = None
            raw_year = result.get("year")
            if raw_year:
                try:
                    result_year = int(str(raw_year)[:4])
                except (ValueError, TypeError):
                    pass

            if name == query:
                if signals.year and result_year and abs(signals.year - result_year) <= 1:
                    confidence = 0.95
                else:
                    confidence = 0.85
            elif query in name or name in query:
                confidence = 0.60
            else:
                confidence = 0.35

            if confidence > best_confidence:
                best_confidence = confidence
                best = result

        if best is None:
            best = results[0]
            best_confidence = 0.35

        slug = best.get("slug", "")
        return ProviderMatch(
            provider=self.name,
            confidence=best_confidence,
            external_ids=ExternalIds(
                extra={
                    "tvdb_id": best.get("tvdb_id"),
                    "tvdb_slug": slug,
                    "tvdb_url": f"https://thetvdb.com/series/{slug}",
                }
            ),
        )


register(TVDBProvider())
