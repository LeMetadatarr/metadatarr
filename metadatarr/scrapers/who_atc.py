"""WHO ATC/DDD classification crawler — migrated onto the engine.

Scrapes the WHO Collaborating Centre for Drug Statistics Methodology ATC/DDD
index (whocc.no/atc_ddd_index). Uses ``unblock_requests`` to handle any JS/CF.

Walks the 5-level ATC hierarchy:
  Level 1: anatomical main group (A-V, 14 groups)
  Level 2: therapeutic subgroup
  Level 3: pharmacological subgroup
  Level 4: chemical subgroup
  Level 5: chemical substance (with DDD values)

Schema per row (level-5 substances):
  atc_code, name, ddd, uom (unit of measure), adm_r (administration route),
  note, level1_code, level1_name, level2_code, level2_name,
  level3_code, level3_name, level4_code, level4_name

The 5-level recursive tree walk has no natural offset/page cursor, so
``fetch(0)`` walks the whole tree and returns every row at once with
``next_cursor=None`` (the pattern the engine docs call out for this exact
scraper). Deviation from the original: the original checkpointed after
every level-4 branch and skipped branches whose ``level4_code`` was already
in the persisted id-set, so an interrupted run resumed mid-tree without
re-fetching completed branches. Because ``fetch`` now returns everything in
one call, a crash mid-walk means the whole tree is re-walked on restart
(rows already in the dataset are still deduped by ``id_field="atc_code"``,
so the emitted dataset content is unaffected — only network cost changes).

Run it::

    python -m metadatarr.scrapers who_atc [--output DIR] [--delay SECS]
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

from metadatarr.scrapers.engine import Source, _HttpMixin, Page, register, run_cli

BASE = "https://www.whocc.no/atc_ddd_index/"


def _parse_child_links(html: str, parent_code: str) -> List[Tuple[str, str]]:
    """Extract direct child (code, name) links for a given parent code.

    ATC hierarchy: L1=1char, L2=3chars, L3=4chars, L4=5chars, L5=7chars.
    Each page lists its parent, itself, and children — filter to children only.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    child_len = {1: 3, 3: 4, 4: 5, 5: 7}.get(len(parent_code), len(parent_code) + 1)
    seen: set = set()
    results = []
    for a in soup.select("a[href*=code]"):
        href = a.get("href", "")
        code_m = re.search(r"[?&]code=([A-Z][A-Z0-9]*)", href)
        if not code_m:
            continue
        code = code_m.group(1)
        name = a.get_text(strip=True)
        if (len(code) == child_len and
                code.startswith(parent_code) and
                code not in seen and
                name and
                "Guidelines" not in name):
            seen.add(code)
            results.append((code, name))
    return results


def _parse_substance_table(html: str, hierarchy: dict) -> List[dict]:
    """Parse the level-5 DDD table from a level-4 page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    rows = []
    # The DDD table uses <td> for all rows (no <th>); header row contains "ATC code"
    for table in soup.select("table"):
        all_tds = [td.get_text(strip=True) for td in table.select("td")]
        if "ATC code" not in all_tds and "DDD" not in all_tds:
            continue
        for tr in table.select("tr"):
            tds = tr.select("td")
            if len(tds) < 4:
                continue
            code = tds[0].get_text(strip=True)
            if not re.match(r"[A-Z]\d{2}[A-Z]{2}\d{2}", code):
                continue
            name = tds[1].get_text(strip=True)
            ddd = tds[2].get_text(strip=True)
            uom = tds[3].get_text(strip=True) if len(tds) > 3 else ""
            adm_r = tds[4].get_text(strip=True) if len(tds) > 4 else ""
            note = tds[5].get_text(strip=True) if len(tds) > 5 else ""
            rows.append({
                "atc_code": code,
                "name": name,
                "ddd": ddd,
                "uom": uom,
                "adm_r": adm_r,
                "note": note,
                **hierarchy,
            })
    return rows


@register
class WhoAtcSource(_HttpMixin, Source):
    name = "who_atc"
    id_field = "atc_code"
    default_delay = 2.0

    user_agent = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
    accept = "text/html,application/xhtml+xml"

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

    def initial_cursor(self) -> int:
        return 0

    def _get_html(self, code: Optional[str] = None) -> str:
        self.throttle.wait()
        params = {"code": code} if code else {}
        r = self.session().get(BASE, params=params, timeout=30)
        r.raise_for_status()
        return r.text

    def _walk_atc(self) -> Iterator[List[dict]]:
        """Walk the full ATC tree, yielding batches of substance rows."""
        html0 = self._get_html()
        from bs4 import BeautifulSoup
        soup0 = BeautifulSoup(html0, "html.parser")
        root_links = []
        for a in soup0.select("a[href*=code]"):
            m = re.search(r"[?&]code=([A-Z])", a.get("href", ""))
            if m:
                code = m.group(1)
                name = a.get_text(strip=True)
                if name and "Guidelines" not in name and code not in {c for c, _ in root_links}:
                    root_links.append((code, name))

        for l1_code, l1_name in root_links:
            html1 = self._get_html(l1_code)
            level2_links = _parse_child_links(html1, l1_code)

            for l2_code, l2_name in level2_links:
                html2 = self._get_html(l2_code)
                level3_links = _parse_child_links(html2, l2_code)

                for l3_code, l3_name in level3_links:
                    html3 = self._get_html(l3_code)
                    level4_links = _parse_child_links(html3, l3_code)

                    for l4_code, l4_name in level4_links:
                        html4 = self._get_html(l4_code)
                        hierarchy = {
                            "level1_code": l1_code, "level1_name": l1_name,
                            "level2_code": l2_code, "level2_name": l2_name,
                            "level3_code": l3_code, "level3_name": l3_name,
                            "level4_code": l4_code, "level4_name": l4_name,
                        }
                        rows = _parse_substance_table(html4, hierarchy)
                        if rows:
                            yield rows

    def fetch(self, cursor: int) -> Page:
        all_rows: List[dict] = []
        for batch in self._walk_atc():
            all_rows.extend(batch)
        return all_rows, None


if __name__ == "__main__":
    raise SystemExit(run_cli(WhoAtcSource))
