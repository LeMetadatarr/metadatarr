"""Tidal album metadata scraper — migrated onto the engine.

Scans tidal.com/album/{id} pages sequentially and extracts metadata from
Open Graph tags. No API key or account required.

The Tidal album ID space is dense in the low millions; IDs that don't map
to albums return the generic TIDAL page title and are skipped.

Schema per row:
  tidal_id, title, artist, description, image_url, url

The cursor is the next Tidal ID to scan (mirrors the original's ``next_id``
checkpoint field). ``id_field=""``: sequential IDs are scanned once per run
and never revisited, so no dedup field is needed (matching ``tidal_artists``).

Run it::

    python -m metadatarr.scrapers tidal_albums [--output DIR] [--delay SECS] [--limit N]
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from metadatarr.scrapers.engine import Page, Source, register, run_cli

BASE = "https://tidal.com/album/{}"
_GENERIC_TITLES = {
    "TIDAL - High Fidelity Music Streaming",
    "TIDAL",
    "Music on TIDAL",
}
_ID_CHUNK = 500  # matches the original's per-batch page size


def _og(html: str, prop: str) -> str:
    m = re.search(rf'og:{re.escape(prop)}" content="([^"]*)"', html)
    return m.group(1) if m else ""


def _html_decode(s: str) -> str:
    s = s.replace("&#39;", "'").replace("&amp;", "&").replace("&quot;", '"')
    s = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), s)
    return s


def _extract_artist(description: str) -> str:
    """Try to extract artist name from OG description like 'Album by Artist'."""
    m = re.search(r'\bby\s+(.+?)(?:\s*[·•|\-]|$)', description, re.IGNORECASE)
    return m.group(1).strip() if m else ""


@register
class TidalAlbumsSource(Source):
    name = "tidal_albums"
    id_field = ""
    default_delay = 1.0

    user_agent = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
    accept = "text/html,application/xhtml+xml"

    def initial_cursor(self) -> int:
        return 1

    def session(self):
        if getattr(self, "_session", None) is None:
            try:
                from unblock_requests import CloudflareSession
                s = CloudflareSession()
            except ImportError:
                import requests
                s = requests.Session()
            s.headers.update({"User-Agent": self.user_agent, "Accept": self.accept})
            self._session = s
        return self._session

    def _fetch_album(self, tidal_id: int) -> Optional[Dict[str, Any]]:
        self.throttle.wait()
        try:
            r = self.session().get(BASE.format(tidal_id), timeout=20, allow_redirects=True)
            if r.status_code != 200:
                return None
        except Exception:
            return None

        html = r.text
        title = _og(html, "title")
        if not title or title in _GENERIC_TITLES:
            return None

        title = _html_decode(title)
        description = _html_decode(_og(html, "description"))
        artist = _extract_artist(description)

        return {
            "tidal_id": tidal_id,
            "title": title,
            "artist": artist,
            "description": description,
            "image_url": _og(html, "image"),
            "url": f"https://tidal.com/album/{tidal_id}",
        }

    def fetch(self, cursor: int) -> Page:
        start = int(cursor)
        rows = []
        end = start + _ID_CHUNK
        for tidal_id in range(start, end):
            row = self._fetch_album(tidal_id)
            if row:
                rows.append(row)
        return rows, end


if __name__ == "__main__":
    raise SystemExit(run_cli(TidalAlbumsSource))
