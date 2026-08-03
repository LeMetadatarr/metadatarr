"""ListenNotes podcast catalog crawler — no API key, pure HTML scraping.

Strategy (mirrors the original exactly):
  1. Paginate ``/best-podcasts/?page={n}`` (curated "best" podcasts, ~45
     pages). Podcast URLs come from JSON-LD ``ItemList`` embedded in each
     page.
  2. Keyword search sweep via ``/search/?q={kw}&type=podcast`` — 200+ seeds —
     to discover podcasts outside the "best" curation (unless ``--no-search``).
  3. For each unique podcast URL, fetch the detail page and extract metadata
     from JSON-LD (schema.org ``PodcastSeries``/``WebPage``) plus meta-tag and
     regex fallbacks.

Neither stage fits the engine's offset/skip model (page-numbered HTML with a
short-page end signal, followed by a keyword×page nested sweep), so
:meth:`fetch` is overridden directly. The cursor is
``{"stage": "listing"|"search"|"done", "listing_page": P, "search_idx": I,
"search_page": P}`` — one page's worth of work per call, mirroring the
original's per-page checkpoint cadence.

Uses ``unblock_requests.CloudflareSession`` if available, else plain
``requests``. Polite default delay 2.5s.

Run it::

    python -m metadatarr.scrapers listennotes_podcasts [--output DIR] [--delay SECS]
                                                        [--no-search]
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

BASE = "https://www.listennotes.com"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Keyword seeds for the /search/ sweep stage
_SEARCH_SEEDS = [
    "comedy", "true crime", "technology", "science", "history", "politics",
    "business", "investing", "health", "fitness", "mental health", "meditation",
    "sports", "football", "basketball", "soccer", "tennis", "golf",
    "music", "jazz", "hip hop", "indie", "rock", "classical",
    "news", "daily news", "politics", "government",
    "education", "learning", "language", "self improvement",
    "fiction", "storytelling", "drama", "mystery", "thriller",
    "horror", "fantasy", "science fiction",
    "interview", "conversation", "panel discussion",
    "entrepreneurship", "startup", "marketing", "leadership",
    "parenting", "kids", "family",
    "food", "cooking", "nutrition",
    "travel", "adventure", "outdoors",
    "philosophy", "spirituality", "religion", "mindfulness",
    "arts", "design", "film", "cinema", "tv", "books",
    "gaming", "video games", "esports",
    "anime", "manga", "pop culture",
    "true crime", "investigation", "journalism",
    "environment", "climate", "sustainability",
    "medicine", "psychology", "neuroscience",
    "economics", "finance", "crypto", "AI", "machine learning",
    "poetry", "literature", "writing",
    "society", "culture", "diversity",
    "documentary", "narrative", "investigative",
    "comedy interview", "improv", "stand-up",
    "running", "yoga", "nutrition",
    "astrology", "tarot", "paranormal",
]


def _extract_jsonld(html: str) -> List[Dict]:
    """Extract all JSON-LD script blocks from a page."""
    blocks = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL):
        try:
            blocks.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            pass
    return blocks


def _urls_from_listing(html: str) -> List[str]:
    """Extract podcast URLs from an ItemList listing page."""
    urls = []
    for block in _extract_jsonld(html):
        if block.get("@type") == "ItemList":
            for item in block.get("itemListElement") or []:
                u = item.get("url", "")
                if "/podcasts/" in u:
                    urls.append(u)
    if not urls:
        urls = list(dict.fromkeys(
            re.findall(r'https://www\.listennotes\.com/podcasts/[^"\'<>\s]+/', html)
        ))
    return list(dict.fromkeys(urls))


def _ln_id_from_url(url: str) -> Optional[str]:
    """Extract ListenNotes podcast ID from a URL slug (last hyphen-segment)."""
    slug = url.rstrip("/").split("/")[-1]
    m = re.search(r"-([A-Za-z0-9_\-]{10,16})$", slug)
    return m.group(1) if m else slug or None


def _parse_detail(html: str, ln_url: str) -> Optional[Dict[str, Any]]:
    """Parse a podcast detail page into a row dict."""
    ln_id = _ln_id_from_url(ln_url)
    if not ln_id:
        return None

    title = None
    description = None
    image = None
    author = None
    language = None
    website = None
    genre_names: List[str] = []

    for block in _extract_jsonld(html):
        btype = block.get("@type", "")
        if btype in ("PodcastSeries", "RadioSeries", "CreativeWorkSeries"):
            title = title or block.get("name")
            description = description or (block.get("description") or "")[:600] or None
            image = image or (block.get("image") or {}).get("url") if isinstance(block.get("image"), dict) else (image or block.get("image"))
            author = author or (block.get("author") or {}).get("name") if isinstance(block.get("author"), dict) else (author or block.get("author"))
            language = language or block.get("inLanguage")
            website = website or block.get("url")
            for g in block.get("genre") or []:
                if isinstance(g, str) and g not in genre_names:
                    genre_names.append(g)

    if not title:
        m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        title = m.group(1) if m else None
    if not description:
        m = re.search(r'<meta(?:\s+name="description"|\s+property="og:description")\s+content="([^"]+)"', html)
        description = (m.group(1) or "")[:600] or None if m else None
    if not image:
        m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        image = m.group(1) if m else None

    listen_score = None
    lm = re.search(r'listenScore:\s*[\'"](\d+)[\'"]', html)
    if lm:
        try:
            listen_score = int(lm.group(1))
        except ValueError:
            pass

    global_rank = None
    rm = re.search(r'globalRank:\s*[\'"]([^\'\"]+)[\'"]', html)
    if rm:
        global_rank = rm.group(1)

    episode_count = None
    em = re.search(r'(\d[\d,]+)\s+episode', html, re.I)
    if em:
        try:
            episode_count = int(em.group(1).replace(",", ""))
        except ValueError:
            pass

    if not title:
        return None

    return {
        "ln_id": ln_id,
        "ln_url": ln_url,
        "title": title,
        "author": author,
        "description": description,
        "image": image,
        "language": language,
        "genres": genre_names,
        "episode_count": episode_count,
        "listen_score": listen_score,
        "global_rank": global_rank,
        "website": website,
        "entity_type": "podcast",
    }


@register
class ListenNotesPodcastsSource(PaginatedJSONSource):
    name = "listennotes_podcasts"
    id_field = "ln_id"
    default_delay = 2.5

    user_agent = _HEADERS["User-Agent"]
    accept = _HEADERS["Accept"]

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self.do_search = True

    @classmethod
    def add_cli_arguments(cls, parser) -> None:
        parser.add_argument("--no-search", dest="do_search", action="store_false", default=True,
                            help="Skip the keyword search sweep (listing only)")

    def configure(self, args) -> None:
        self.do_search = getattr(args, "do_search", True)

    def session(self):
        if self._session is None:
            try:
                from unblock_requests import CloudflareSession
                s = CloudflareSession()
            except Exception:
                import requests
                s = requests.Session()
            s.headers.update(_HEADERS)
            self._session = s
        return self._session

    def initial_cursor(self) -> Dict[str, Any]:
        return {"stage": "listing", "listing_page": 1, "search_idx": 0, "search_page": 1}

    def _get(self, url: str):
        self.throttle.wait()
        try:
            resp = self.session().get(url, timeout=self.timeout)
        except Exception:
            return None
        if resp.status_code == 429:
            retry = int(resp.headers.get("Retry-After", 60))
            time.sleep(retry)
            return None
        if resp.status_code in (403, 404, 410, 400):
            return None
        resp.raise_for_status()
        return resp

    def _process_urls(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Fetch detail pages for URLs not already harvested; return new rows."""
        already = getattr(self, "_seen", set()) or set()
        rows: List[Dict[str, Any]] = []
        for url in urls:
            ln_id = _ln_id_from_url(url)
            if not ln_id or ln_id in already:
                continue
            resp = self._get(url)
            if resp is None:
                continue
            row = _parse_detail(resp.text, url)
            if row and row.get("title"):
                rows.append(row)
                already.add(ln_id)
        return rows

    def fetch(self, cursor: Dict[str, Any]):
        stage = cursor.get("stage", "listing")

        if stage == "listing":
            listing_page = int(cursor.get("listing_page", 1))
            url = f"{BASE}/best-podcasts/"
            if listing_page > 1:
                url += f"?page={listing_page}"

            resp = self._get(url)
            if resp is None:
                next_cursor = ({"stage": "search", "listing_page": listing_page,
                               "search_idx": 0, "search_page": 1}
                               if self.do_search else None)
                return [], next_cursor

            pod_urls = _urls_from_listing(resp.text)
            if not pod_urls:
                next_cursor = ({"stage": "search", "listing_page": listing_page,
                               "search_idx": 0, "search_page": 1}
                               if self.do_search else None)
                return [], next_cursor

            rows = self._process_urls(pod_urls)

            if len(pod_urls) < 10:
                next_cursor = ({"stage": "search", "listing_page": listing_page + 1,
                               "search_idx": 0, "search_page": 1}
                               if self.do_search else None)
            else:
                next_cursor = {"stage": "listing", "listing_page": listing_page + 1,
                               "search_idx": 0, "search_page": 1}
            return rows, next_cursor

        if stage == "search" and self.do_search:
            search_idx = int(cursor.get("search_idx", 0))
            search_page = int(cursor.get("search_page", 1))

            if search_idx >= len(_SEARCH_SEEDS):
                return [], None

            kw = _SEARCH_SEEDS[search_idx]
            url = f"{BASE}/search/?q={kw.replace(' ', '+')}&type=podcast&page_number={search_page}"
            resp = self._get(url)

            def _next_seed():
                nxt = search_idx + 1
                return ({"stage": "search", "listing_page": 0,
                        "search_idx": nxt, "search_page": 1}
                        if nxt < len(_SEARCH_SEEDS) else None)

            if resp is None:
                return [], _next_seed()

            pod_urls = _urls_from_listing(resp.text)
            if not pod_urls:
                return [], _next_seed()

            rows = self._process_urls(pod_urls)

            if len(pod_urls) < 5 or search_page >= 19:
                next_cursor = _next_seed()
            else:
                next_cursor = {"stage": "search", "listing_page": 0,
                               "search_idx": search_idx, "search_page": search_page + 1}
            return rows, next_cursor

        return [], None


if __name__ == "__main__":
    raise SystemExit(run_cli(ListenNotesPodcastsSource))
