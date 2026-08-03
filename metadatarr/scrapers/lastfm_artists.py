"""Last.fm artist catalog crawler.

Iterates ~200 music tags via ``tag.getTopArtists``, enriching each artist via
``artist.getInfo``. Requires the ``LASTFM_API_KEY`` environment variable — if
unset, the crawl does nothing (matching the original's early-exit-with-error
rather than raising).

Pagination is a nested walk (tag × page) capped by Last.fm's own
``totalPages`` attribute or ``MAX_PAGES_PER_TAG``, whichever is smaller — not
the engine's offset/short-page shape — so :meth:`fetch` is overridden
directly. The cursor is ``{"tag_idx": i, "tag_page": p}``.

Deduplication is by artist **name** (case-insensitively), not by the engine's
``id_field`` (mbid), because many artists have no mbid: the original scanned
already-written rows for ``name`` at startup and skipped repeats regardless
of mbid. :meth:`run` is overridden to reproduce that exact scan into
``self._seen_names`` before delegating to the engine loop; ``id_field="mbid"``
is kept in addition as a (harmless, redundant) cross-check consistent with
other artist scrapers in this codebase (e.g. ``musicbrainz_artists``).

Deviation from the original: a transient API failure (429 / network error)
now advances to the next page rather than being retried in the same
in-process loop iteration — the engine checkpoints every page including
failures, so forward progress on restart is at least as good as before.

Environment:
    LASTFM_API_KEY  - required, from https://www.last.fm/api/account/create

Run it::

    LASTFM_API_KEY=xxx python -m metadatarr.scrapers lastfm_artists [--output DIR] [--delay SECS]
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from metadatarr.scrapers._checkpoint import default_output_dir
from metadatarr.scrapers.engine import Source, _HttpMixin, register, run_cli

LOG = logging.getLogger("metadatarr.scrapers")

BASE = "http://ws.audioscrobbler.com/2.0/"
PAGE_SIZE = 50  # max per Last.fm tag.getTopArtists page
MAX_PAGES_PER_TAG = 20  # 20 x 50 = 1000 top artists per tag

# ~200 tags covering all major music genres + moods + eras
TAGS = [
    # Main genres
    "rock", "pop", "jazz", "classical", "electronic", "hip-hop", "r&b",
    "country", "folk", "blues", "metal", "punk", "reggae", "soul", "funk",
    "indie", "alternative", "dance", "house", "techno", "trance", "ambient",
    "experimental", "avant-garde", "gospel", "opera", "acoustic", "new age",
    # Sub-genres
    "death metal", "black metal", "heavy metal", "thrash metal", "doom metal",
    "progressive rock", "post-rock", "art rock", "classic rock", "hard rock",
    "soft rock", "psychedelic", "shoegaze", "dream pop", "britpop",
    "post-punk", "new wave", "synthpop", "darkwave", "industrial",
    "deep house", "progressive house", "tech house", "drum and bass",
    "dubstep", "electro", "minimal", "breakbeat", "jungle", "garage",
    "trap", "grime", "lo-fi", "boom bap", "conscious hip-hop",
    "bluegrass", "americana", "outlaw country", "nashville", "tejano",
    "bossa nova", "samba", "salsa", "cumbia", "flamenco", "fado",
    "afrobeats", "afropop", "highlife", "juju", "soukous", "kwaito",
    "k-pop", "j-pop", "j-rock", "c-pop", "mandopop", "cantopop",
    "bolero", "tango", "merengue", "bachata", "vallenato",
    "celtic", "folk rock", "world music", "latin jazz", "nu jazz",
    "smooth jazz", "bebop", "free jazz", "swing", "big band",
    "baroque", "romantic", "contemporary classical", "minimalism",
    "film score", "video game music", "musical theatre", "choral",
    "trip-hop", "downtempo", "chillout", "lounge", "rave",
    "noise", "post-metal", "sludge", "stoner rock", "grunge",
    "emo", "screamo", "hardcore", "metalcore", "deathcore",
    "power metal", "symphonic metal", "gothic metal", "folk metal",
    "ska", "rocksteady", "dub", "dancehall", "roots reggae",
    "gospel", "spiritual", "christian", "worship",
    "comedy", "spoken word", "poetry", "children music",
    # Moods/descriptors
    "melancholy", "uplifting", "energetic", "chill", "romantic", "aggressive",
    "atmospheric", "dark", "happy", "sad",
    # Eras
    "60s", "70s", "80s", "90s", "2000s", "2010s",
]


def _int(val: Any) -> Optional[int]:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


@register
class LastfmArtistsSource(_HttpMixin, Source):
    name = "lastfm_artists"
    id_field = "mbid"
    default_delay = 0.25  # Last.fm allows 5 req/s

    base = BASE
    accept = "application/json"

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self._api_key = os.environ.get("LASTFM_API_KEY", "")
        self._seen_names: set = set()

    def initial_cursor(self) -> Dict[str, int]:
        return {"tag_idx": 0, "tag_page": 1}

    def _api(self, method: str, **params: Any) -> Optional[Dict[str, Any]]:
        self.throttle.wait()
        try:
            r = self.session().get(
                self.base,
                params={"method": method, "api_key": self._api_key,
                        "format": "json", **params},
                timeout=20,
            )
            if r.status_code == 429:
                LOG.warning("[%s] 429 rate-limit — sleeping 30s", self.name)
                time.sleep(30)
                return None
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            LOG.warning("[%s] %s error: %s", self.name, method, exc)
            return None

    def _parse_artist_info(self, info: Dict[str, Any]) -> Dict[str, Any]:
        artist = info.get("artist") or {}
        stats = artist.get("stats") or {}
        tags = artist.get("tags") or {}
        bio = artist.get("bio") or {}
        similar = artist.get("similar") or {}

        tag_list = [t.get("name") for t in (tags.get("tag") or []) if t.get("name")]
        similar_list = [s.get("name") for s in (similar.get("artist") or []) if s.get("name")]

        summary = bio.get("summary") or ""
        if "<a href" in summary:
            summary = summary[:summary.find("<a href")].strip()

        return {
            "mbid": artist.get("mbid") or None,
            "name": artist.get("name"),
            "url": artist.get("url"),
            "listeners": _int(stats.get("listeners")),
            "playcount": _int(stats.get("playcount")),
            "tags": tag_list[:15],
            "similar_artists": similar_list[:10],
            "bio_summary": summary[:600] if summary else None,
            "entity_type": "musician",
        }

    def _advance(self, tag_idx: int, tag_page: int) -> Optional[Dict[str, int]]:
        """Cursor for "move past this (tag, page)" — next page, or next tag."""
        next_page = tag_page + 1
        if next_page <= MAX_PAGES_PER_TAG:
            return {"tag_idx": tag_idx, "tag_page": next_page}
        next_tag = tag_idx + 1
        return {"tag_idx": next_tag, "tag_page": 1} if next_tag < len(TAGS) else None

    def fetch(self, cursor: Dict[str, int]):
        if not self._api_key:
            LOG.error("[%s] set LASTFM_API_KEY environment variable", self.name)
            return [], None

        tag_idx = int(cursor.get("tag_idx", 0))
        tag_page = int(cursor.get("tag_page", 1))
        if tag_idx >= len(TAGS):
            return [], None
        tag = TAGS[tag_idx]

        data = self._api("tag.gettopartists", tag=tag, limit=PAGE_SIZE, page=tag_page)
        if data is None:
            return [], self._advance(tag_idx, tag_page)

        top = data.get("topartists") or {}
        artists: List[Dict[str, Any]] = top.get("artist") or []
        attrs = top.get("@attr") or {}

        if not artists:
            next_tag = tag_idx + 1
            return [], ({"tag_idx": next_tag, "tag_page": 1} if next_tag < len(TAGS) else None)

        rows: List[Dict[str, Any]] = []
        for a in artists:
            name = a.get("name")
            if not name or name.lower() in self._seen_names:
                continue
            self._seen_names.add(name.lower())

            info_data = self._api("artist.getinfo", artist=name, autocorrect=1)
            if info_data:
                parsed = self._parse_artist_info(info_data)
            else:
                parsed = {
                    "mbid": a.get("mbid") or None,
                    "name": name,
                    "url": a.get("url"),
                    "listeners": _int(a.get("listeners")),
                    "playcount": None,
                    "tags": [tag],
                    "similar_artists": [],
                    "bio_summary": None,
                    "entity_type": "musician",
                }
            rows.append(parsed)

        total_pages = int(attrs.get("totalPages", tag_page))
        if tag_page >= total_pages or tag_page >= MAX_PAGES_PER_TAG:
            next_tag = tag_idx + 1
            next_cursor = {"tag_idx": next_tag, "tag_page": 1} if next_tag < len(TAGS) else None
        else:
            next_cursor = {"tag_idx": tag_idx, "tag_page": tag_page + 1}
        return rows, next_cursor

    def run(self, output_dir=None, *, limit: int = 0) -> int:
        out_dir = output_dir or default_output_dir()
        dataset_path = out_dir / f"{self.dataset_name or self.name}.jsonl"
        if dataset_path.exists():
            with dataset_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if obj.get("name"):
                            self._seen_names.add(obj["name"].lower())
                    except Exception:
                        pass
        return super().run(output_dir, limit=limit)


if __name__ == "__main__":
    raise SystemExit(run_cli(LastfmArtistsSource))
