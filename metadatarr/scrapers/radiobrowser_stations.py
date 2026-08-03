"""Radio Browser station crawler.

Fetches all stations from the Radio Browser community database (completely
free, no API key required), via the DNS-based load-balanced endpoint.
Offset-paginated; the response is a bare JSON array (not wrapped in a
results key) and a short page is the end-of-catalog signal, so
:meth:`fetch` is overridden directly. On a request error the original
rotates through a small pool of known mirror servers and retries — that
retry loop is reproduced here, bounded (the shared engine can't retry a
cursor forever the way the standalone script's ``while True`` did).

API docs: https://api.radio-browser.info/

Run it::

    python -m metadatarr.scrapers radiobrowser_stations [--output DIR] [--limit N] [--delay SECS]
"""
from __future__ import annotations

import socket
import time
from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

PAGE_SIZE = 1000

_KNOWN_SERVERS = [
    "https://de1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
]


def _get_base_url() -> str:
    """Return a working Radio Browser server URL."""
    try:
        ips = socket.getaddrinfo("all.api.radio-browser.info", 443, socket.AF_INET)
        if ips:
            ip = ips[0][4][0]
            try:
                host = socket.gethostbyaddr(ip)[0]
                return f"https://{host}"
            except Exception:
                pass
    except Exception:
        pass
    return _KNOWN_SERVERS[0]


@register
class RadioBrowserStationsSource(PaginatedJSONSource):
    name = "radiobrowser_stations"
    id_field = "stationuuid"
    default_delay = 0.5

    page_size = PAGE_SIZE
    user_agent = "metadatarr-scraper/1.0 (https://github.com/TigreGotico)"

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self._base_url: Optional[str] = None

    def initial_cursor(self) -> int:
        return 0

    def map_row(self, s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        tags = [t.strip() for t in (s.get("tags") or "").split(",") if t.strip()]
        languages = [l.strip() for l in (s.get("languagecodes") or "").split(",") if l.strip()]
        row = {
            "stationuuid": s.get("stationuuid"),
            "name": s.get("name"),
            "url": s.get("url"),
            "url_resolved": s.get("url_resolved"),
            "homepage": s.get("homepage"),
            "favicon": s.get("favicon"),
            "country": s.get("country"),
            "countrycode": s.get("countrycode"),
            "state": s.get("state"),
            "language": s.get("language"),
            "language_codes": languages,
            "tags": tags[:20],
            "codec": s.get("codec"),
            "bitrate": s.get("bitrate"),
            "hls": s.get("hls", False),
            "votes": s.get("votes"),
            "clickcount": s.get("clickcount"),
            "clicktrend": s.get("clicktrend"),
            "last_check_ok": s.get("lastcheckok"),
            "entity_type": "radio_station",
        }
        # original only kept stations with a name
        return row if row["name"] else None

    def fetch(self, cursor: int):
        offset = int(cursor or 0)
        if self._base_url is None:
            self._base_url = _get_base_url()

        stations: Optional[List[Dict[str, Any]]] = None
        last_exc: Optional[Exception] = None
        for _attempt in range(len(_KNOWN_SERVERS) + 1):
            self.throttle.wait()
            try:
                resp = self.session().get(
                    f"{self._base_url}/json/stations",
                    params={
                        "limit": PAGE_SIZE,
                        "offset": offset,
                        "order": "stationuuid",
                        "hidebroken": "false",
                    },
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                stations = resp.json()
                break
            except Exception as exc:
                last_exc = exc
                idx = (_KNOWN_SERVERS.index(self._base_url)
                       if self._base_url in _KNOWN_SERVERS else 0)
                self._base_url = _KNOWN_SERVERS[(idx + 1) % len(_KNOWN_SERVERS)]
                time.sleep(5)
        if stations is None:
            raise last_exc  # type: ignore[misc]

        if not stations:
            return [], None

        rows = []
        for s in stations:
            row = self.map_row(s)
            if row is not None:
                rows.append(row)

        next_cursor = None if len(stations) < PAGE_SIZE else offset + PAGE_SIZE
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(RadioBrowserStationsSource))
