"""Tidal artist metadata scraper — migrated onto the engine.

Scans tidal.com/artist/{id} pages sequentially and extracts metadata from
Open Graph tags. No API key or account required.

The Tidal artist ID space is dense from ~997 onward; IDs that don't map to
artists return the generic TIDAL page title and are skipped.

Schema per row:
  tidal_id, name, description, image_url, url

The cursor is the next Tidal ID to scan (mirrors the original's ``next_id``
checkpoint field). ``id_field=""``: unlike the original's checkpoint-carried
"seen_sample" (a 500-entry ring buffer only meant to dedup the tail of a
resumed run), the engine already only fetches each ID once per run, and
sequential IDs are never revisited within a run, so no dedup field is needed
here (a synthetic id_field would just needlessly grow the on-disk id-set).

Run it::

    python -m metadatarr.scrapers tidal_artists [--output DIR] [--delay SECS] [--limit N]
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from metadatarr.scrapers.engine import Page, Source, register, run_cli

BASE = "https://tidal.com/artist/{}"
# Page title returned when an ID doesn't map to an artist
_GENERIC_TITLES = {
    "TIDAL - High Fidelity Music Streaming",
    "TIDAL",
    "Music on TIDAL",
}
_ID_CHUNK = 1000  # matches the original's per-batch page size


def _og(html: str, prop: str) -> str:
    m = re.search(rf'og:{re.escape(prop)}" content="([^"]*)"', html)
    return m.group(1) if m else ""


@register
class TidalArtistsSource(Source):
    name = "tidal_artists"
    id_field = ""
    default_delay = 1.0

    user_agent = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
    accept = "text/html,application/xhtml+xml"

    default_start = 1
    default_end = 2_000_000

    def __init__(self, **kw):
        super().__init__(**kw)
        self.start = self.default_start
        self.end = self.default_end

    @classmethod
    def add_cli_arguments(cls, parser):
        parser.add_argument("--start", type=int, default=cls.default_start,
                            help="first Tidal ID to scan")
        parser.add_argument("--end", type=int, default=cls.default_end,
                            help="last Tidal ID to scan")

    def configure(self, args):
        self.start = getattr(args, "start", self.default_start)
        self.end = getattr(args, "end", self.default_end)

    def initial_cursor(self) -> int:
        return self.start

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

    def _fetch_artist(self, tidal_id: int) -> Optional[Dict[str, Any]]:
        self.throttle.wait()
        try:
            r = self.session().get(BASE.format(tidal_id), timeout=20, allow_redirects=True)
            if r.status_code != 200:
                return None
        except Exception:
            return None

        html = r.text
        name = _og(html, "title")
        if not name or name in _GENERIC_TITLES:
            return None
        name = name.replace("&#39;", "'").replace("&amp;", "&").replace("&quot;", '"')
        name = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), name)

        return {
            "tidal_id": tidal_id,
            "name": name,
            "description": _og(html, "description"),
            "image_url": _og(html, "image"),
            "url": f"https://tidal.com/artist/{tidal_id}",
        }

    def fetch(self, cursor: int) -> Page:
        start = int(cursor)
        if start > self.end:
            return [], None
        rows = []
        chunk_end = min(start + _ID_CHUNK, self.end + 1)
        for tidal_id in range(start, chunk_end):
            row = self._fetch_artist(tidal_id)
            if row:
                rows.append(row)
        next_cursor = None if chunk_end > self.end else chunk_end
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(TidalArtistsSource))
