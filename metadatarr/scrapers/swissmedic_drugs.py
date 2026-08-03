"""Swissmedic (Switzerland) approved drug list scraper — migrated onto the engine.

Downloads the official "Zugelassene Arzneimittel" xlsx from swissmedic.ch,
yielding German/French drug names, registration numbers, ATC-like
therapeutic codes, and dispensing categories.

Schema per row:
  zulassungsnummer, bezeichnung, zulassungsinhaber, heilmittelcode,
  abgabekategorie, erstzulassung, language

Single whole-dataset fetch — the XLSX is scraped/downloaded once, cached to
``{output_dir}/_swissmedic_drugs.xlsx`` (exactly like the original), then
every row is parsed and returned in one shot with ``next_cursor=None``,
mirroring how ``who_atc`` is migrated. TLS verification is disabled,
matching the original's ``verify=False`` + ``urllib3.disable_warnings``.

Run it::

    python -m metadatarr.scrapers swissmedic_drugs [--output DIR]
"""
from __future__ import annotations

from typing import Any, List

from metadatarr.scrapers.engine import Source, _HttpMixin, Page, register, run_cli

# Landing page — scrape this to find the current xlsx URL
LISTS_PAGE = "https://www.swissmedic.ch/swissmedic/de/home/services/listen_neu.html"
# Fallback / confirmed URL (2026-06-30)
FALLBACK_XLSX_URL = (
    "https://www.swissmedic.ch/dam/swissmedic/de/dokumente/internetlisten/"
    "zugelassene_arzneimittel_ham_ind.xlsx.download.xlsx/Zugelassene_Arzneimittel_HAM.xlsx"
)
HEADER_ROW = 6   # 0-indexed; row 7 in spreadsheet terms
DATA_START = 7   # 0-indexed first data row


def _find_xlsx_url(html: str) -> str:
    """Scrape the Swissmedic lists page to find the current xlsx download URL."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "zugelassene_arzneimittel" in href.lower() and ".xlsx" in href.lower():
            if href.startswith("http"):
                return href
            return "https://www.swissmedic.ch" + href
    return FALLBACK_XLSX_URL


def _parse_date(val) -> str:
    """Convert openpyxl date/datetime or string to ISO date string."""
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.date().isoformat() if hasattr(val, "date") else val.isoformat()
    return str(val).strip()


def _parse_workbook(ws) -> List[dict]:
    """Parse rows from the Swissmedic XLSX worksheet."""
    rows_out = []
    row_idx = 0
    for row in ws.iter_rows(values_only=True):
        if row_idx < DATA_START:
            row_idx += 1
            continue
        row_idx += 1

        # Col A: Zulassungs-Nummer, C: Bezeichnung, D: Inhaber, E: Heilmittelcode,
        # G: Abgabekategorie Arzneimittel, H: Erstzulassungsdatum
        zulnr = str(row[0]).strip() if row[0] is not None else ""
        bezeichnung = str(row[2]).strip() if row[2] is not None else ""
        inhaber = str(row[3]).strip() if row[3] is not None else ""
        heilmittel = str(row[4]).strip() if row[4] is not None else ""
        abgabe = str(row[6]).strip() if row[6] is not None else ""
        erstzul = _parse_date(row[7]) if len(row) > 7 else ""

        if not bezeichnung:
            continue

        rows_out.append({
            "zulassungsnummer": zulnr,
            "bezeichnung": bezeichnung,
            "zulassungsinhaber": inhaber,
            "heilmittelcode": heilmittel,
            "abgabekategorie": abgabe,
            "erstzulassung": erstzul,
            "language": "de-CH",
        })
    return rows_out


@register
class SwissmedicDrugsSource(_HttpMixin, Source):
    name = "swissmedic_drugs"
    id_field = ""
    default_delay = 0.0

    user_agent = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
    accept = "text/html,application/xhtml+xml"

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
        import openpyxl

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        output_dir = self._output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        cache_xlsx = output_dir / "_swissmedic_drugs.xlsx"

        if not cache_xlsx.exists():
            self.throttle.wait()
            r = self.session().get(LISTS_PAGE, timeout=30, verify=False)
            r.raise_for_status()
            xlsx_url = _find_xlsx_url(r.text)

            self.throttle.wait()
            r2 = self.session().get(xlsx_url, timeout=120, verify=False, stream=True)
            r2.raise_for_status()
            data = b""
            for chunk in r2.iter_content(65536):
                data += chunk
            cache_xlsx.write_bytes(data)

        wb = openpyxl.load_workbook(cache_xlsx, read_only=True, data_only=True)
        ws = wb.active
        rows = _parse_workbook(ws)
        wb.close()

        return rows, None


if __name__ == "__main__":
    raise SystemExit(run_cli(SwissmedicDrugsSource))
