"""GRLS (Russia) drug registry scraper — migrated onto the engine.

Searches rosminzdrav.ru GRLS for drugs by Cyrillic letter (a-ya) and Latin
letter (a-z) via ASP.NET WebForms POST, parses result HTML tables. The
cursor is an index into the combined Cyrillic+Latin query list.

Schema per row:
  reg_number, trade_name, inn_mnn, manufacturer, country,
  form, dosage, query_letter, language, source

Deviation from the original: on a failed viewstate/search request for one
letter, the original logged a warning, saved a checkpoint that still pointed
at the *failed* letter (so a restart would retry it), and then continued its
in-process loop to the next letter. The engine's cursor model has one
cursor value per step, so a failure here is treated as "no rows for this
letter" and the cursor still advances to the next letter — matching the
original's within-run continuation, but not its restart-retries-failed-
letter behaviour. Row schema/content for successfully-fetched letters is
unchanged.

Run it::

    python -m metadatarr.scrapers grls_drugs [--output DIR] [--delay SECS]
"""
from __future__ import annotations

from typing import Any, Dict, List

from metadatarr.scrapers.engine import Source, _HttpMixin, Page, register, run_cli

_SEARCH_URL = "https://grls.rosminzdrav.ru/GRLS.aspx"
_CYRILLIC = list("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
_LATIN = list("abcdefghijklmnopqrstuvwxyz")
_QUERIES = _CYRILLIC + _LATIN


def _get_viewstate(session, url: str):
    """Fetch the GRLS search page and extract ASP.NET hidden form fields."""
    from bs4 import BeautifulSoup

    r = session.get(url, timeout=60, verify=False)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    fields = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR",
                  "__VIEWSTATEENCRYPTED", "__EVENTVALIDATION"):
        tag = soup.find("input", {"name": name})
        if tag:
            fields[name] = tag.get("value", "")
    return fields, r.text


def _parse_results(html: str) -> List[Dict[str, Any]]:
    """Parse the result HTML table from a GRLS search response."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    rows = []

    # GRLS renders results in a GridView table; look for a table with > 1 rows
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        # Check if header row contains drug-registry-like columns
        header_text = trs[0].get_text(" ", strip=True).lower()
        if not any(kw in header_text for kw in ("регистр", "наименование", "препарат", "лекарств")):
            continue
        # Extract column indices from header
        headers = [th.get_text(strip=True).lower() for th in trs[0].find_all(["th", "td"])]
        for tr in trs[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if not cells:
                continue
            row: Dict[str, Any] = {"language": "ru", "source": "grls"}
            # Try to map cells to known fields by header position
            for i, cell in enumerate(cells):
                if i >= len(headers):
                    break
                h = headers[i]
                if "регистр" in h or "номер" in h:
                    row["reg_number"] = cell
                elif "торгов" in h or "наименован" in h:
                    row["trade_name"] = cell
                elif "мнн" in h or "inn" in h or "международн" in h:
                    row["inn_mnn"] = cell
                elif "произв" in h or "завод" in h:
                    row["manufacturer"] = cell
                elif "стран" in h:
                    row["country"] = cell
                elif "форм" in h:
                    row["form"] = cell
                elif "доз" in h:
                    row["dosage"] = cell
            # Fallback positional mapping (GRLS typical column order)
            if "reg_number" not in row and len(cells) >= 4:
                row.setdefault("reg_number", cells[0])
                row.setdefault("trade_name", cells[1])
                row.setdefault("inn_mnn", cells[2])
                row.setdefault("manufacturer", cells[3])
                if len(cells) > 4:
                    row.setdefault("country", cells[4])
                if len(cells) > 5:
                    row.setdefault("form", cells[5])
                if len(cells) > 6:
                    row.setdefault("dosage", cells[6])
            if row.get("trade_name") or row.get("reg_number"):
                rows.append(row)
        if rows:
            break  # found the right table
    return rows


@register
class GrlsDrugsSource(_HttpMixin, Source):
    name = "grls_drugs"
    id_field = ""
    default_delay = 1.0

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
            s.headers["User-Agent"] = self.user_agent
            s.verify = False
            self._session = s
        return self._session

    def initial_cursor(self) -> int:
        return 0

    def fetch(self, cursor: int) -> Page:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        idx = int(cursor)
        if idx >= len(_QUERIES):
            return [], None

        letter = _QUERIES[idx]
        next_cursor = idx + 1

        self.throttle.wait()
        try:
            fields, _ = _get_viewstate(self.session(), _SEARCH_URL)
        except Exception:
            return [], next_cursor

        payload = {
            **fields,
            "ctl00$plate$txtMNN": letter,
            "ctl00$plate$btnSearch": "Найти",
        }
        self.throttle.wait()
        try:
            r = self.session().post(_SEARCH_URL, data=payload, timeout=60, verify=False)
            r.raise_for_status()
        except Exception:
            return [], next_cursor

        rows = _parse_results(r.text)
        for row in rows:
            row["query_letter"] = letter

        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(GrlsDrugsSource))
