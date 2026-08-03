"""Podcast catalog crawler — no API key, multiple free Apple/iTunes sources.

Sources (in order, each optional via ``--sources``):
  1. ``charts``  — iTunes top-podcasts RSS feed, swept over every
     country x genre combo (~100 per chart x 60+ genres x 50 countries).
  2. ``search``  — iTunes Search API by genre ID x a handful of seed terms.
  3. ``browse``  — Apple Podcasts genre top-list, swept over 30 countries.

All free, no auth. Deduped globally by iTunes collection ID (handled by the
engine via :attr:`id_field`), matching the original's shared ``seen`` set
across all three sources.

This doesn't fit a single offset/partition cursor: it's three independent
nested sweeps, each with its own indices and its own row shape, so
:meth:`fetch` is overridden directly. The cursor is
``{"stage": "charts"|"search"|"browse"|"done", ...stage indices}``. Stage
granularity matches the original's checkpoint granularity: ``charts``
checkpoints after every single country/genre HTTP call; ``search`` and
``browse`` checkpoint once per genre (after sweeping all terms/countries for
it), so one :meth:`fetch` call there does several HTTP requests, exactly as
the original's inner loops did between checkpoint saves.

Run it::

    python -m metadatarr.scrapers podcastindex_podcasts [--output DIR] [--delay SECS]
                                                         [--sources charts,search,browse]
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

# iTunes top-podcasts RSS feed (country + genre, no auth, max 200 per request).
CHARTS_COUNTRIES = [
    "us", "gb", "ca", "au", "de", "fr", "es", "it", "jp", "kr",
    "br", "mx", "in", "ru", "nl", "se", "no", "dk", "fi", "pl",
    "pt", "ar", "co", "cl", "za", "ng", "eg", "tr", "sa", "ae",
    "sg", "hk", "tw", "th", "id", "ph", "my", "nz", "ie", "at",
    "ch", "be", "cz", "hu", "ro", "ua", "gr", "il", "pk", "vn",
]
CHARTS_SIZE = 200  # max per iTunes RSS call

# iTunes podcast genre IDs (from Apple's genre taxonomy)
ITUNES_GENRES: List[Tuple[int, str]] = [
    (26, "Podcasts"),
    (1301, "Arts"),
    (1306, "Books"),
    (1402, "Design"),
    (1405, "Fashion & Beauty"),
    (1417, "Food"),
    (1309, "Performing Arts"),
    (1310, "Visual Arts"),
    (1321, "Business"),
    (1322, "Careers"),
    (1323, "Entrepreneurship"),
    (1325, "Investing"),
    (1326, "Management"),
    (1456, "Marketing"),
    (1327, "Non-Profit"),
    (1303, "Comedy"),
    (1424, "Comedy Interviews"),
    (1425, "Improv"),
    (1426, "Stand-Up"),
    (1304, "Education"),
    (1427, "Courses"),
    (1468, "How-To"),
    (1469, "Language Learning"),
    (1412, "Self-Improvement"),
    (1483, "Fiction"),
    (1484, "Drama"),
    (1485, "Science Fiction"),
    (1305, "Kids & Family"),
    (1440, "Parenting"),
    (1441, "Pets & Animals"),
    (1470, "Stories for Kids"),
    (1502, "Government"),
    (1307, "Health & Fitness"),
    (1471, "Alternative Health"),
    (1472, "Fitness"),
    (1473, "Medicine"),
    (1474, "Mental Health"),
    (1475, "Nutrition"),
    (1476, "Sexuality"),
    (1308, "History"),
    (1502, "Government"),
    (1314, "Music"),
    (1477, "Music Commentary"),
    (1478, "Music History"),
    (1479, "Music Interviews"),
    (1315, "News"),
    (1428, "Business News"),
    (1480, "Daily News"),
    (1430, "Entertainment News"),
    (1431, "News Commentary"),
    (1432, "Politics"),
    (1433, "Sports News"),
    (1434, "Tech News"),
    (1316, "Religion & Spirituality"),
    (1438, "Buddhism"),
    (1439, "Christianity"),
    (1440, "Hinduism"),
    (1441, "Islam"),
    (1442, "Judaism"),
    (1443, "Spirituality"),
    (1317, "Science"),
    (1444, "Astronomy"),
    (1446, "Earth Sciences"),
    (1447, "Life Sciences"),
    (1448, "Mathematics"),
    (1449, "Natural Sciences"),
    (1450, "Nature"),
    (1451, "Physics"),
    (1452, "Social Sciences"),
    (1318, "Society & Culture"),
    (1453, "Documentary"),
    (1454, "Personal Journals"),
    (1455, "Philosophy"),
    (1320, "Sports"),
    (1462, "Baseball"),
    (1463, "Basketball"),
    (1464, "Cricket"),
    (1465, "Fantasy Sports"),
    (1466, "Football"),
    (1467, "Golf"),
    (1468, "Hockey"),
    (1469, "Rugby"),
    (1470, "Running"),
    (1471, "Soccer"),
    (1472, "Swimming"),
    (1473, "Tennis"),
    (1474, "Volleyball"),
    (1475, "Wilderness"),
    (1476, "Amateur"),
    (1319, "Technology"),
    (1446, "Gadgets"),
    (1448, "Tech News"),
    (1450, "Podcasting"),
    (1452, "Software"),
    (1488, "True Crime"),
    (1309, "TV & Film"),
    (1486, "After Shows"),
    (1487, "Film History"),
    (1489, "Film Interviews"),
    (1490, "Film Reviews"),
    (1491, "TV Reviews"),
    (1502, "Leisure"),
    (1493, "Animation & Manga"),
    (1459, "Automotive"),
    (1460, "Aviation"),
    (1461, "Crafts"),
    (1494, "Games"),
    (1495, "Hobbies"),
    (1498, "Video Games"),
]
_UNIQUE_GENRES: List[Tuple[int, str]] = list({gid: name for gid, name in ITUNES_GENRES}.items())
_COMBOS: List[Tuple[int, str]] = [(0, "All")] + _UNIQUE_GENRES
_SEARCH_TERMS = ["", "a", "the", "podcast", "show", "talk", "radio", "daily", "weekly"]
_BROWSE_COUNTRIES = CHARTS_COUNTRIES[:30]


def map_chart_row(entry: Dict[str, Any], country: str, genre_name: str) -> Optional[Dict[str, Any]]:
    """Parse an iTunes RSS feed entry (im:name / im:artist / id[attributes])."""
    id_attrs = (entry.get("id") or {}).get("attributes") or {}
    iid = id_attrs.get("im:id")
    if not iid:
        return None
    name_obj = entry.get("im:name") or {}
    artist_obj = entry.get("im:artist") or {}
    img_list = entry.get("im:image") or []
    img = img_list[-1].get("label") if img_list else None
    link_obj = entry.get("link") or {}
    link_attrs = link_obj.get("attributes") or {}
    return {
        "itunes_id": iid,
        "title": name_obj.get("label") if isinstance(name_obj, dict) else str(name_obj),
        "author": artist_obj.get("label") if isinstance(artist_obj, dict) else None,
        "image": img,
        "genres": [genre_name] if genre_name else [],
        "url": link_attrs.get("href"),
        "description": None,
        "language": None,
        "episode_count": None,
        "explicit": None,
        "feed_url": None,
        "country_charts": [country],
        "source": "itunes_rss",
        "entity_type": "podcast",
    }


def map_search_row(e: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    iid = e.get("collectionId")
    if not iid:
        return None
    return {
        "itunes_id": str(iid),
        "title": e.get("collectionName"),
        "author": e.get("artistName"),
        "image": e.get("artworkUrl600") or e.get("artworkUrl100"),
        "genres": e.get("genres") or [],
        "url": e.get("collectionViewUrl"),
        "description": None,
        "language": None,
        "episode_count": e.get("trackCount"),
        "explicit": (e.get("contentAdvisoryRating") or "").lower() == "explicit",
        "feed_url": e.get("feedUrl"),
        "country_charts": [],
        "source": "itunes_search",
        "entity_type": "podcast",
    }


def map_browse_row(entry: Dict[str, Any], country: str, genre_name: str) -> Optional[Dict[str, Any]]:
    id_attrs = (entry.get("id") or {}).get("attributes") or {}
    iid = id_attrs.get("im:id")
    if not iid:
        return None
    title_obj = entry.get("im:name") or entry.get("title") or {}
    artist_obj = entry.get("im:artist") or {}
    genre_obj = (entry.get("category") or {}).get("attributes") or {}
    img_list = entry.get("im:image") or []
    img = img_list[-1].get("label") if img_list else None
    return {
        "itunes_id": iid,
        "title": title_obj.get("label") if isinstance(title_obj, dict) else str(title_obj),
        "author": artist_obj.get("label") if isinstance(artist_obj, dict) else None,
        "image": img,
        "genres": [genre_obj.get("term")] if genre_obj.get("term") else [genre_name],
        "url": None,
        "description": None,
        "language": None,
        "episode_count": None,
        "explicit": None,
        "feed_url": None,
        "country_charts": [country],
        "source": "apple_browse",
        "entity_type": "podcast",
    }


@register
class PodcastIndexPodcastsSource(PaginatedJSONSource):
    name = "podcastindex_podcasts"
    id_field = "itunes_id"
    default_delay = 0.5

    user_agent = "iTunes/12.12 (Macintosh; OS X 12.0)"

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self.sources: List[str] = ["charts", "search", "browse"]

    @classmethod
    def add_cli_arguments(cls, parser) -> None:
        parser.add_argument("--sources", default="charts,search,browse",
                            help="Comma-separated: charts,search,browse (default: all)")

    def configure(self, args) -> None:
        sources = getattr(args, "sources", None)
        if sources:
            self.sources = [s.strip() for s in sources.split(",") if s.strip()]

    def initial_cursor(self) -> Dict[str, Any]:
        return self._start_of("charts")

    def _start_of(self, stage: str) -> Dict[str, Any]:
        order = ["charts", "search", "browse"]
        idx = order.index(stage)
        for candidate in order[idx:]:
            if candidate in self.sources:
                if candidate == "charts":
                    return {"stage": "charts", "cidx": 0, "gidx": 0}
                return {"stage": candidate, "gidx": 0}
        return {"stage": "done"}

    def _get(self, url: str) -> Optional[Any]:
        self.throttle.wait()
        try:
            resp = self.session().get(url, timeout=20)
            if resp.status_code in (400, 404):
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def _fetch_charts_step(self, cursor: Dict[str, Any]):
        cidx = int(cursor["cidx"])
        gidx = int(cursor["gidx"])
        country = CHARTS_COUNTRIES[cidx]
        gid, gname = _COMBOS[gidx]

        if gid == 0:
            url = f"https://itunes.apple.com/{country}/rss/toppodcasts/limit={CHARTS_SIZE}/explicit=true/json"
        else:
            url = f"https://itunes.apple.com/{country}/rss/toppodcasts/limit={CHARTS_SIZE}/genre={gid}/explicit=true/json"

        data = self._get(url)
        entries = ((data or {}).get("feed") or {}).get("entry") or []
        rows = []
        for e in entries:
            row = map_chart_row(e, country, gname)
            if row is not None:
                rows.append(row)

        next_gidx = gidx + 1
        if next_gidx < len(_COMBOS):
            next_cursor = {"stage": "charts", "cidx": cidx, "gidx": next_gidx}
        else:
            next_cidx = cidx + 1
            if next_cidx < len(CHARTS_COUNTRIES):
                next_cursor = {"stage": "charts", "cidx": next_cidx, "gidx": 0}
            else:
                next_cursor = self._start_of("search")
        return rows, next_cursor

    def _fetch_search_step(self, cursor: Dict[str, Any]):
        gidx = int(cursor["gidx"])
        gid, gname = _UNIQUE_GENRES[gidx]

        rows = []
        for term in _SEARCH_TERMS:
            params = {"media": "podcast", "entity": "podcast", "genreId": gid, "limit": 200}
            if term:
                params["term"] = term
            self.throttle.wait()
            try:
                resp = self.session().get("https://itunes.apple.com/search", params=params, timeout=30)
                if resp.status_code == 403:
                    time.sleep(10)
                    continue
                resp.raise_for_status()
                results = resp.json().get("results") or []
            except Exception:
                continue
            for e in results:
                row = map_search_row(e)
                if row is not None:
                    rows.append(row)

        next_gidx = gidx + 1
        if next_gidx < len(_UNIQUE_GENRES):
            next_cursor = {"stage": "search", "gidx": next_gidx}
        else:
            next_cursor = self._start_of("browse")
        return rows, next_cursor

    def _fetch_browse_step(self, cursor: Dict[str, Any]):
        gidx = int(cursor["gidx"])
        gid, gname = _UNIQUE_GENRES[gidx]

        rows = []
        for country in _BROWSE_COUNTRIES:
            url = f"https://itunes.apple.com/{country}/rss/toppodcasts/limit=200/genre={gid}/explicit=true/json"
            data = self._get(url)
            entries = ((data or {}).get("feed") or {}).get("entry") or []
            for e in entries:
                row = map_browse_row(e, country, gname)
                if row is not None:
                    rows.append(row)

        next_gidx = gidx + 1
        if next_gidx < len(_UNIQUE_GENRES):
            next_cursor = {"stage": "browse", "gidx": next_gidx}
        else:
            next_cursor = None
        return rows, next_cursor

    def fetch(self, cursor: Dict[str, Any]):
        stage = cursor.get("stage", "done")
        if stage == "charts":
            return self._fetch_charts_step(cursor)
        if stage == "search":
            return self._fetch_search_step(cursor)
        if stage == "browse":
            return self._fetch_browse_step(cursor)
        return [], None


if __name__ == "__main__":
    raise SystemExit(run_cli(PodcastIndexPodcastsSource))
