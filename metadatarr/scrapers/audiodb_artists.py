"""TheAudioDB artist crawler — no API key, HTML seed + free JSON API + graph-walk.

Strategy (multi-stage, mirrors the original exactly):
  1. ``seed``  — scrape ``/chart_artists`` for the top popular artist IDs.
  2. ``crawl`` — BFS: pop an ID, fetch ``artist.php?i={id}`` for full
     metadata, then scrape that artist's HTML page for related-artist links
     and enqueue any unseen ones. Continues until the queue is empty.
  3. ``fill``  — optional (``--fill``): after the graph-walk, sequentially
     probe IDs between the lowest and highest IDs seen so far (+5000), to
     catch artists no page linked to.

The whole crawl is a stateful graph walk (queue + stage), not offset/partition
pagination, so :meth:`fetch` is overridden directly and the cursor carries
the queue/stage/probe-position — same shape as the original's checkpoint.

Deviation from the original (documented, since the engine's ``fetch`` has no
access to the persisted id set the way ``run()`` does): the original's
``fill`` stage computes its probe range from the *entire* on-disk dedup set
(``min`` and ``max`` of every ID ever seen, across restarts). This port
tracks the min/max of IDs seen *during the current process* (seed + crawl)
instead, since a bare ``Source.fetch`` isn't handed the engine's dedup set.
For an uninterrupted run this is identical; after a restart directly into an
in-progress ``fill`` stage, the resumed bounds come from the checkpoint's own
``fill_id``/``lo``/``hi`` (also carried forward, as in the original), so only
a *fresh* process resuming mid-fill without those cached bounds would recompute
a narrower range than the original.

Run it::

    python -m metadatarr.scrapers audiodb_artists [--output DIR] [--limit N] [--delay SECS] [--fill]
"""
from __future__ import annotations

import re
from typing import Any, Deque, Dict, List, Optional
from collections import deque

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

API_BASE = "https://www.theaudiodb.com/api/v1/json/2"
SITE_BASE = "https://www.theaudiodb.com"


def _extract_ids_from_html(html: str) -> List[str]:
    """Extract artist IDs from any AudioDB HTML page."""
    return list(dict.fromkeys(re.findall(r"/artist/(\d+)-", html)))


@register
class AudioDBArtistsSource(PaginatedJSONSource):
    name = "audiodb_artists"
    id_field = "adb_id"
    default_delay = 1.0

    user_agent = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
    accept = "*/*"

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self.do_fill = False
        self._seen_ids: set = set()

    @classmethod
    def add_cli_arguments(cls, parser) -> None:
        parser.add_argument("--fill", action="store_true",
                            help="After graph-walk, sequentially probe IDs between "
                                 "min..max+5000 (slow)")

    def configure(self, args) -> None:
        self.do_fill = getattr(args, "fill", False)

    def session(self):
        if self._session is None:
            try:
                from unblock_requests import CloudflareSession
                s = CloudflareSession()
            except Exception:
                import requests
                s = requests.Session()
            s.headers.update({"User-Agent": self.user_agent, "Accept": self.accept})
            self._session = s
        return self._session

    def initial_cursor(self) -> Dict[str, Any]:
        return {"stage": "seed", "queue": []}

    def map_row(self, a: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        aid = a.get("idArtist")
        name = a.get("strArtist")
        if not aid or not name:
            return None
        return {
            "adb_id": str(aid),
            "mb_id": a.get("strMusicBrainzID"),
            "name": name,
            "alternate_name": a.get("strArtistAlternate"),
            "formed_year": a.get("intFormedYear"),
            "born_year": a.get("intBornYear"),
            "disbanded_year": a.get("intDiedYear"),
            "country": a.get("strCountry"),
            "country_code": a.get("strCountryCode"),
            "style": a.get("strStyle"),
            "genre": a.get("strGenre"),
            "mood": a.get("strMood"),
            "website": a.get("strWebsite"),
            "facebook": a.get("strFacebook"),
            "twitter": a.get("strTwitter"),
            "biography_en": (a.get("strBiographyEN") or "")[:600] or None,
            "members": a.get("intMembers"),
            "label": a.get("strLabel"),
            "gender": a.get("strGender"),
            "logo_url": a.get("strArtistLogo"),
            "thumb_url": a.get("strArtistThumb"),
            "banner_url": a.get("strArtistBanner"),
            "fanart_url": a.get("strArtistFanart"),
        }

    def _api_get(self, path: str, params: Dict) -> Optional[Dict]:
        self.throttle.wait()
        try:
            resp = self.session().get(f"{API_BASE}/{path}", params=params, timeout=20)
            if resp.status_code in (404, 429):
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def _html_get(self, url: str) -> Optional[str]:
        self.throttle.wait()
        try:
            resp = self.session().get(url, timeout=20)
            if resp.status_code in (404, 410):
                return None
            resp.raise_for_status()
            return resp.text
        except Exception:
            return None

    def _track(self, aid: str) -> None:
        if aid.isdigit():
            self._seen_ids.add(int(aid))

    def _fetch_artist_row(self, adb_id: str) -> Optional[Dict[str, Any]]:
        data = self._api_get("artist.php", {"i": adb_id})
        artists = (data or {}).get("artists") or [] if data else []
        return self.map_row(artists[0]) if artists else None

    def fetch(self, cursor: Dict[str, Any]):
        stage = cursor.get("stage", "seed")

        if stage == "seed":
            html = self._html_get(f"{SITE_BASE}/chart_artists")
            seed_ids = _extract_ids_from_html(html) if html else []
            for sid in seed_ids:
                self._track(sid)
            return [], {"stage": "crawl", "queue": seed_ids}

        if stage == "crawl":
            queue: Deque[str] = deque(cursor.get("queue") or [])
            if not queue:
                next_cursor = ({"stage": "fill", "queue": [], "fill_id": 0}
                               if self.do_fill else None)
                return [], next_cursor

            adb_id = queue.popleft()
            self._track(adb_id)
            row = self._fetch_artist_row(adb_id)

            rows = []
            if row is not None:
                rows.append(row)
                related = _extract_ids_from_html(self._html_get(f"{SITE_BASE}/artist/{adb_id}") or "")
                for rid in related:
                    self._track(rid)
                    if rid not in queue:
                        queue.append(rid)

            return rows, {"stage": "crawl", "queue": list(queue)}

        if stage == "fill":
            fill_id = int(cursor.get("fill_id", 0))
            lo = cursor.get("lo")
            hi = cursor.get("hi")
            if lo is None or hi is None:
                if self._seen_ids:
                    lo = fill_id or min(self._seen_ids)
                    hi = max(self._seen_ids) + 5000
                else:
                    lo, hi = 100000, 200000
            probe_id = fill_id if fill_id >= lo else lo

            if probe_id >= hi:
                return [], None

            row = self._fetch_artist_row(str(probe_id))
            rows = [row] if row is not None else []
            return rows, {"stage": "fill", "queue": [], "fill_id": probe_id + 1,
                          "lo": lo, "hi": hi}

        return [], None


if __name__ == "__main__":
    raise SystemExit(run_cli(AudioDBArtistsSource))
