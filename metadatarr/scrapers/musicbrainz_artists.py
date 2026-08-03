"""MusicBrainz artist bulk crawler.

Paginates the full MusicBrainz artist index (2M+ entries) using the lucene
wildcard query ``artist?query=*`` with offset-based pagination. The catalog's
``count`` field (returned on every page) is the authoritative end-of-catalog
signal — not a short page — so :meth:`fetch` is overridden directly.

Environment:
    MB_CONTACT  - your e-mail / app URL for the User-Agent header (recommended
                  by MusicBrainz so they can contact you if you hammer the API)

Run it::

    python -m metadatarr.scrapers musicbrainz_artists [--output DIR] [--limit N] [--delay SECS]
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

PAGE_SIZE = 100
BASE_URL = "https://musicbrainz.org/ws/2/artist"


@register
class MusicBrainzArtistsSource(PaginatedJSONSource):
    name = "musicbrainz_artists"
    id_field = "mb_id"
    default_delay = 1.1

    base = BASE_URL
    results_key = "artists"
    page_size = PAGE_SIZE

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        contact = os.environ.get("MB_CONTACT", "metadatarr-scraper/1.0")
        self.user_agent = f"metadatarr-scraper/1.0 ( {contact} )"

    def initial_cursor(self) -> int:
        return 0

    def map_row(self, a: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        begin = a.get("life-span") or {}
        return {
            "mb_id": a.get("id"),
            "name": a.get("name"),
            "sort_name": a.get("sort-name"),
            "type": a.get("type"),
            "gender": a.get("gender"),
            "country": a.get("country"),
            "area": (a.get("area") or {}).get("name"),
            "begin_date": begin.get("begin"),
            "end_date": begin.get("end"),
            "ended": begin.get("ended"),
            "disambiguation": a.get("disambiguation"),
            "aliases": [al.get("name") for al in (a.get("aliases") or []) if al.get("name")],
            "tags": [t.get("name") for t in (a.get("tags") or []) if t.get("name")],
            "ipi_codes": a.get("ipis") or [],
            "isni_codes": a.get("isnis") or [],
        }

    def fetch(self, cursor: int):
        offset = int(cursor or 0)
        params = {
            "query": "type:person OR type:group OR type:orchestra OR type:choir "
                     "OR type:character OR type:other",
            "fmt": "json",
            "limit": PAGE_SIZE,
            "offset": offset,
        }
        data = self.get_json(self.base, params)
        artists = data.get("artists") or []
        count = data.get("count", 0)

        if not artists:
            return [], None

        rows = []
        for a in artists:
            row = self.map_row(a)
            if row is not None:
                rows.append(row)

        next_offset = offset + PAGE_SIZE
        next_cursor = None if next_offset >= count else next_offset
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(MusicBrainzArtistsSource))
