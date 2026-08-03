"""PMDA (Japan) approved drug list scraper — migrated onto the engine.

Scrapes the PMDA English review pages for approved drugs, yielding brand
names, non-proprietary (INN/generic) names, and approval dates.

Pages scraped:
  https://www.pmda.go.jp/english/review-services/reviews/approved-information/drugs/0001.html
  https://www.pmda.go.jp/english/review-services/reviews/approved-information/drugs/0002.html
  ... (stops on 404)

Schema per row:
  brand_name, nonproprietary_name, approved_in, language, country

Deviation from the original: the original walked pages forever, stopping
only on an HTTP 404. :class:`PaginatedHTMLSource` normally stops on an empty
parsed page instead, which would misfire on any page that legitimately has
no matching table. ``fetch`` is overridden to talk to the session directly
and replicate the original's "stop on 404 only" behaviour, while everything
else (session/session/parsing) still rides the engine's HTML pagination
class.

Run it::

    python -m metadatarr.scrapers pmda_drugs [--output DIR] [--delay SECS]
"""
from __future__ import annotations

from typing import List

from metadatarr.scrapers.engine import PaginatedHTMLSource, Page, register, run_cli

BASE_URL = (
    "https://www.pmda.go.jp/english/review-services/reviews/"
    "approved-information/drugs/{page:04d}.html"
)
# Expected table headers (case-insensitive partial match)
EXPECTED_HEADERS = {"brand name", "non-proprietary name", "approved in"}


def _parse_page(soup) -> List[dict]:
    """Extract drug rows from a PMDA approved-drug HTML page."""
    results = []

    for table in soup.find_all("table"):
        # Find the header row
        headers = []
        header_row = table.find("tr")
        if not header_row:
            continue
        for th in header_row.find_all(["th", "td"]):
            headers.append(th.get_text(strip=True).lower())

        # Check this table has the expected headers
        if not EXPECTED_HEADERS.issubset(set(headers)):
            continue

        # Map column indices
        try:
            brand_idx = next(i for i, h in enumerate(headers) if "brand name" in h)
            inn_idx = next(i for i, h in enumerate(headers) if "non-proprietary" in h)
            approved_idx = next(i for i, h in enumerate(headers) if "approved in" in h)
        except StopIteration:
            continue

        # Parse data rows (skip header row)
        tbody = table.find("tbody")
        row_source = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

        for tr in row_source:
            cells = tr.find_all(["td", "th"])
            if len(cells) <= max(brand_idx, inn_idx, approved_idx):
                continue
            brand = cells[brand_idx].get_text(strip=True)
            inn = cells[inn_idx].get_text(strip=True)
            approved = cells[approved_idx].get_text(strip=True)
            if not brand and not inn:
                continue
            results.append({
                "brand_name": brand,
                "nonproprietary_name": inn,
                "approved_in": approved,
                "language": "en",
                "country": "JP",
            })

    return results


@register
class PMDADrugsSource(PaginatedHTMLSource):
    name = "pmda_drugs"
    id_field = ""
    default_delay = 0.0

    user_agent = (
        "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
    )
    accept = "text/html,application/xhtml+xml"

    def parse_page(self, soup, page: int) -> List[dict]:
        return _parse_page(soup)

    def fetch(self, cursor: int) -> Page:
        from bs4 import BeautifulSoup

        page = int(cursor)
        url = BASE_URL.format(page=page)
        self.throttle.wait()
        resp = self.session().get(url, timeout=self.timeout)
        if resp.status_code == 404:
            return [], None
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = _parse_page(soup)
        return rows, page + 1


if __name__ == "__main__":
    raise SystemExit(run_cli(PMDADrugsSource))
