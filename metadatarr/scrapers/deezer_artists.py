"""Deezer artist catalog scraper.

Uses the public Deezer API (no auth required) to crawl the catalog by walking
artist IDs sequentially — Deezer IDs are dense from ~1 onward, and each id is
a single ``GET /artist/{id}`` call rather than an offset-paginated listing, so
:meth:`fetch` is overridden directly. The cursor is the next Deezer id to try;
each call walks a 1000-id chunk (matching the original's checkpoint interval)
and returns whatever artists resolved in that range.

A 404/non-200 response or a body with an ``"error"`` key means "no artist at
this id" (very common — ids are sparse in practice despite being dense in
principle) and is silently skipped, exactly as the original did: no retry,
just move to the next id.

Schema per row:
  deezer_id, name, picture_url, nb_album, nb_fan, url

Run it::

    python -m metadatarr.scrapers deezer_artists [--output DIR] [--start ID] [--end ID] [--delay SECS]
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from metadatarr.scrapers.engine import Source, _HttpMixin, register, run_cli

BASE = "https://api.deezer.com/artist/{}"
ID_CHUNK = 1000
DEFAULT_START = 1
DEFAULT_END = 2_000_000


@register
class DeezerArtistsSource(_HttpMixin, Source):
    name = "deezer_artists"
    id_field = "deezer_id"
    default_delay = 1.0

    base = BASE
    chunk = ID_CHUNK

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self.start = DEFAULT_START
        self.end = DEFAULT_END

    @classmethod
    def add_cli_arguments(cls, parser) -> None:
        parser.add_argument("--start", type=int, default=DEFAULT_START,
                            help="first Deezer artist id to fetch")
        parser.add_argument("--end", type=int, default=DEFAULT_END,
                            help="last Deezer artist id to fetch")

    def configure(self, args) -> None:
        self.start = args.start
        self.end = args.end

    def initial_cursor(self) -> int:
        return self.start

    def map_row(self, deezer_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "deezer_id": deezer_id,
            "name": data.get("name"),
            "picture_url": data.get("picture_big") or data.get("picture"),
            "nb_album": data.get("nb_album"),
            "nb_fan": data.get("nb_fan"),
            "url": data.get("link"),
        }

    def _fetch_artist(self, deezer_id: int) -> Optional[Dict[str, Any]]:
        self.throttle.wait()
        try:
            r = self.session().get(self.base.format(deezer_id), timeout=20)
            if r.status_code != 200:
                return None
            data = r.json()
        except Exception:
            return None
        if "error" in data:
            return None
        name = data.get("name")
        if not name:
            return None
        return self.map_row(deezer_id, data)

    def fetch(self, cursor: int):
        start = int(cursor)
        if start > self.end:
            return [], None
        end = min(start + self.chunk - 1, self.end)
        rows = []
        for deezer_id in range(start, end + 1):
            row = self._fetch_artist(deezer_id)
            if row:
                rows.append(row)
        next_cursor = end + 1 if end < self.end else None
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(DeezerArtistsSource))
