"""FASS (Sweden) drug product scraper — migrated onto the engine.

Swedish drug database — Swedish-language brand names, dosage forms, NPL IDs.
Scrapes alphabetical listing pages a-z, one page per letter (no numeric
pagination), so the cursor is a letter index rather than an offset.

Schema per row:
  trade_name, dosage_form, manufacturer, npl_id, product_url, language

Mirrors the original's per-page (per-letter) in-memory dedup of
``(trade_name, npl_id)`` pairs — reset every run, not persisted across
restarts, matching the original which recreated ``seen = set()`` at the
start of every ``crawl()`` call. TLS verification is disabled, matching the
original's ``verify=False`` + ``urllib3.disable_warnings``.

Run it::

    python -m metadatarr.scrapers fass_drugs [--output DIR] [--delay SECS]
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import Source, _HttpMixin, Page, register, run_cli

BASE_URL = "https://fass.se/products/{letter}"
LETTERS = list("abcdefghijklmnopqrstuvwxyz")
NPL_RE = re.compile(r"/product/(\d+)")


def _parse_letter_page(soup, seen: set) -> List[Dict[str, Any]]:
    """Extract drug rows from a FASS letter listing page."""
    rows = []
    for a in soup.select("li a"):
        href = a.get("href", "")
        m = NPL_RE.search(href)
        if not m:
            continue
        npl_id = m.group(1)
        product_url = href if href.startswith("http") else f"https://fass.se{href}"
        li_text = a.get_text(strip=True)

        # Trade name: from the heading preceding the <ul> that contains this <li>
        parent_li = a.parent  # <li>
        parent_ul = parent_li.parent  # <ul>
        prev = parent_ul.find_previous_sibling()
        trade_name = prev.get_text(strip=True) if prev else ""

        key = (trade_name, npl_id)
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "trade_name": trade_name,
            "dosage_form": li_text,
            "manufacturer": "",
            "npl_id": npl_id,
            "product_url": product_url,
            "language": "sv",
        })
    return rows


@register
class FassDrugsSource(_HttpMixin, Source):
    name = "fass_drugs"
    id_field = ""
    default_delay = 0.3

    user_agent = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
    accept = "text/html,application/xhtml+xml"

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self._seen: set = set()

    def session(self):
        if self._session is None:
            import requests
            s = requests.Session()
            s.headers["User-Agent"] = self.user_agent
            s.verify = False
            self._session = s
        return self._session

    def initial_cursor(self) -> int:
        return 0

    def fetch(self, cursor: int) -> Page:
        import urllib3
        from bs4 import BeautifulSoup
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        idx = int(cursor)
        if idx >= len(LETTERS):
            return [], None

        letter = LETTERS[idx]
        url = BASE_URL.format(letter=letter)
        self.throttle.wait()
        r = self.session().get(url, timeout=60, verify=False)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        rows = _parse_letter_page(soup, self._seen)

        return rows, idx + 1


if __name__ == "__main__":
    raise SystemExit(run_cli(FassDrugsSource))
