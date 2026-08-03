"""codifa.it (Italy) drug scraper — migrated onto the engine.

Two-phase scrape, mirrored per letter:
  Phase 1  — letter pages  https://www.codifa.it/farmaci/{a-z}
             collect brand name + slug for every drug listed
  Phase 2  — detail pages  https://www.codifa.it/farmaci/{letter}/{slug}
             add principio_attivo, classe_terapeutica, atc, forma_farmaceutica

Schema per row (final, enriched):
  brand_name, slug, href, letter, language, source,
  principio_attivo, classe_terapeutica, atc, forma_farmaceutica
  (detail keys are only present when found on the detail page, exactly as
  in the original — no key is forced to a default).

Deviation from the original: the original wrote phase-1 (listing-only) rows
to the dataset immediately, then separately enriched them into a sidecar
``codifa_drugs_enriched.jsonl`` file with its own resumable offset
checkpoint (every 200 detail pages). The engine has one output dataset per
source, so ``fetch`` fetches a whole letter's listing *and* every one of its
detail pages in a single cursor step, returning only the final merged rows.
This means the intermediate un-enriched rows are never written, and a crash
mid-letter re-does that whole letter on restart instead of resuming from a
detail-page offset — the emitted row schema is unchanged.

Uses ``unblock_requests.CloudflareSession`` (mirroring the original) with
TLS verification disabled, matching the original's ``verify=False``.

Run it::

    python -m metadatarr.scrapers codifa_drugs [--output DIR] [--delay SECS]
"""
from __future__ import annotations

from typing import Any, Dict, List

from metadatarr.scrapers.engine import Source, _HttpMixin, Page, register, run_cli

_BASE = "https://www.codifa.it"
_LETTERS = list("abcdefghijklmnopqrstuvwxyz")

_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"


def _letter_url(letter: str) -> str:
    return f"{_BASE}/farmaci/{letter}"


def _detail_url(href: str) -> str:
    return f"{_BASE}{href}"


def _parse_letter_page(html: str, letter: str) -> List[Dict[str, Any]]:
    """Extract drug links from a letter index page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    results = []
    for a in soup.select(f'a[href*="/farmaci/{letter}/"]'):
        text = a.get_text(strip=True)
        href = a.get("href", "")
        if len(text) <= 3:
            continue
        slug = href.rstrip("/").split("/")[-1]
        results.append({"brand_name": text, "slug": slug, "href": href})
    return results


def _parse_detail_page(html: str) -> Dict[str, Any]:
    """Extract drug details from a codifa detail page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    detail: Dict[str, Any] = {}

    # Try definition list (<dl><dt>Label</dt><dd>Value</dd>)
    dt_tags = soup.find_all("dt")
    for dt in dt_tags:
        label = dt.get_text(strip=True).lower()
        dd = dt.find_next_sibling("dd")
        value = dd.get_text(strip=True) if dd else ""
        if "principio" in label or "attivo" in label:
            detail["principio_attivo"] = value
        elif "classe" in label and "terapeutica" in label:
            detail["classe_terapeutica"] = value
        elif "atc" in label:
            detail["atc"] = value
        elif "forma" in label and "farmaceutica" in label:
            detail["forma_farmaceutica"] = value

    # Fallback: table rows
    if not detail:
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).lower()
                value = cells[1].get_text(strip=True)
                if "principio" in label or "attivo" in label:
                    detail["principio_attivo"] = value
                elif "classe" in label and "terapeutica" in label:
                    detail["classe_terapeutica"] = value
                elif "atc" in label:
                    detail["atc"] = value
                elif "forma" in label:
                    detail["forma_farmaceutica"] = value

    return detail


@register
class CodifaDrugsSource(_HttpMixin, Source):
    name = "codifa_drugs"
    id_field = ""
    default_delay = 0.5

    user_agent = _UA
    accept = "text/html,application/xhtml+xml"

    def session(self):
        if self._session is None:
            try:
                from unblock_requests import CloudflareSession
                s = CloudflareSession()
            except Exception:
                import requests
                s = requests.Session()
            s.headers["User-Agent"] = self.user_agent
            s.verify = False
            self._session = s
        return self._session

    def initial_cursor(self) -> int:
        return 0

    def _get(self, url: str):
        self.throttle.wait()
        r = self.session().get(url, timeout=60, verify=False)
        r.raise_for_status()
        return r

    def fetch(self, cursor: int) -> Page:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        idx = int(cursor)
        if idx >= len(_LETTERS):
            return [], None

        letter = _LETTERS[idx]
        r = self._get(_letter_url(letter))
        drugs = _parse_letter_page(r.text, letter)

        rows = []
        for d in drugs:
            r2 = None
            try:
                r2 = self._get(_detail_url(d["href"]))
                detail = _parse_detail_page(r2.text)
            except Exception:
                detail = {}
            row = {
                "brand_name": d["brand_name"],
                "slug": d["slug"],
                "href": d["href"],
                "letter": letter,
                "language": "it",
                "source": "codifa",
                **detail,
            }
            rows.append(row)

        return rows, idx + 1


if __name__ == "__main__":
    raise SystemExit(run_cli(CodifaDrugsSource))
