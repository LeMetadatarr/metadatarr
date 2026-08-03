"""MusicBrainz release-group bulk crawler.

Crawls the full MusicBrainz release-group catalog (albums, singles, EPs,
compilations, live albums, ...) with offset-based pagination. Like
``musicbrainz_artists``, the catalog's ``count`` field is the authoritative
end-of-catalog signal, so :meth:`fetch` is overridden directly.

Environment:
    MB_CONTACT  - your e-mail / app URL for the User-Agent header.

Run it::

    python -m metadatarr.scrapers musicbrainz_releases [--output DIR] [--limit N] [--delay SECS]
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

PAGE_SIZE = 100
BASE_URL = "https://musicbrainz.org/ws/2/release-group"


@register
class MusicBrainzReleasesSource(PaginatedJSONSource):
    name = "musicbrainz_releases"
    id_field = "mb_release_group_id"
    default_delay = 1.1

    base = BASE_URL
    results_key = "release-groups"
    page_size = PAGE_SIZE

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        contact = os.environ.get("MB_CONTACT", "metadatarr-scraper/1.0")
        self.user_agent = f"metadatarr-scraper/1.0 ( {contact} )"

    def initial_cursor(self) -> int:
        return 0

    def map_row(self, rg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ac = rg.get("artist-credit") or []
        artist_names = [
            c.get("artist", {}).get("name") or c.get("name")
            for c in ac
            if isinstance(c, dict)
        ]
        artist_ids = [
            c.get("artist", {}).get("id")
            for c in ac
            if isinstance(c, dict) and c.get("artist")
        ]
        return {
            "mb_release_group_id": rg.get("id"),
            "title": rg.get("title"),
            "type": rg.get("primary-type"),
            "secondary_types": rg.get("secondary-types") or [],
            "first_release_date": rg.get("first-release-date"),
            "artist_names": [n for n in artist_names if n],
            "artist_mb_ids": [i for i in artist_ids if i],
            "tags": [t.get("name") for t in (rg.get("tags") or []) if t.get("name")],
            "disambiguation": rg.get("disambiguation"),
        }

    def fetch(self, cursor: int):
        offset = int(cursor or 0)
        params = {
            "query": "releasegroup:*",
            "fmt": "json",
            "limit": PAGE_SIZE,
            "offset": offset,
        }
        data = self.get_json(self.base, params)
        items = data.get("release-groups") or []
        count = data.get("count", 0)

        if not items:
            return [], None

        rows = []
        for rg in items:
            row = self.map_row(rg)
            if row is not None:
                rows.append(row)

        next_offset = offset + PAGE_SIZE
        next_cursor = None if next_offset >= count else next_offset
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(MusicBrainzReleasesSource))
