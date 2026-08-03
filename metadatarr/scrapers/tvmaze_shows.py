"""TVmaze show catalog crawler.

Pages through https://api.tvmaze.com/shows?page=N (250 shows/page, free,
no auth). Stops when the endpoint returns HTTP 404 - which the engine's
shared ``get_json`` retry wrapper would treat as a hard error rather than a
clean end-of-catalog signal, so :meth:`fetch` hits the session directly to
preserve that semantic (cursor is the page number).

Run it::

    python -m metadatarr.scrapers tvmaze_shows [--output DIR] [--limit N] [--delay SECS]
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

BASE_URL = "https://api.tvmaze.com/shows"

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return _TAG_RE.sub("", text).strip() or None


@register
class TVMazeShowsSource(PaginatedJSONSource):
    name = "tvmaze_shows"
    id_field = "tvmaze_id"
    default_delay = 0.3

    base = BASE_URL

    def initial_cursor(self) -> int:
        return 0

    def map_row(self, s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if s.get("id") is None:
            return None
        network = s.get("network") or s.get("webChannel") or {}
        country = (network.get("country") or {}).get("code")
        ext = s.get("externals") or {}
        rating = s.get("rating") or {}
        schedule = s.get("schedule") or {}
        return {
            "tvmaze_id": s.get("id"),
            "name": s.get("name"),
            "type": s.get("type"),
            "language": s.get("language"),
            "genres": s.get("genres") or [],
            "status": s.get("status"),
            "runtime": s.get("runtime"),
            "average_runtime": s.get("averageRuntime"),
            "premiered": s.get("premiered"),
            "ended": s.get("ended"),
            "network_name": network.get("name"),
            "network_country": country,
            "rating_average": rating.get("average"),
            "schedule_time": schedule.get("time"),
            "schedule_days": schedule.get("days") or [],
            "summary": _strip_html(s.get("summary")),
            "official_site": s.get("officialSite"),
            "imdb_id": ext.get("imdb"),
            "thetvdb_id": ext.get("thetvdb"),
            "tvrage_id": ext.get("tvrage"),
            "image_medium": (s.get("image") or {}).get("medium"),
        }

    def fetch(self, cursor: int):
        page = int(cursor)
        self.throttle.wait()
        resp = self.session().get(self.base, params={"page": page}, timeout=self.timeout)

        if resp.status_code == 404:
            return [], None
        resp.raise_for_status()

        shows = resp.json()
        if not shows:
            return [], None

        rows = []
        for s in shows:
            row = self.map_row(s)
            if row is not None:
                rows.append(row)
        return rows, page + 1


if __name__ == "__main__":
    raise SystemExit(run_cli(TVMazeShowsSource))
