"""TITCK (Turkey) drug product scraper — migrated onto the engine.

Turkish national drug registry — Turkish-language brand names, ATC codes,
companies, prescription types. Downloads the most recent weekly XLSX from
TITCK's listing page and parses it with openpyxl.

Schema per row:
  ilac_adi, barkod, atc_kodu, atc_adi, firma_adi, recete_turu, durumu, language

This is a single whole-dataset fetch (find XLSX link -> download -> parse
every row) with no natural pagination, so ``fetch(0)`` returns every row at
once with ``next_cursor=None``, mirroring how ``who_atc`` is migrated.
Rows whose status column ("durumu") isn't ``"Aktif"`` are dropped, exactly
as in the original. TLS verification is disabled, matching the original's
``verify=False`` + ``urllib3.disable_warnings``.

Run it::

    python -m metadatarr.scrapers titck_drugs [--output DIR]
"""
from __future__ import annotations

from typing import Any, List

from metadatarr.scrapers.engine import Source, _HttpMixin, Page, register, run_cli

LISTING_URL = "https://www.titck.gov.tr/dinamikmodul/43"


def _parse_workbook(ws) -> List[dict]:
    """Parse rows from the TITCK XLSX worksheet (header row 3, data from row 4)."""
    rows_out = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        if not any(row):
            continue
        durumu = str(row[6]).strip() if row[6] is not None else ""
        if durumu != "Aktif":
            continue
        rows_out.append({
            "ilac_adi":    str(row[0]).strip() if row[0] is not None else "",
            "barkod":      str(row[1]).strip() if row[1] is not None else "",
            "atc_kodu":    str(row[2]).strip() if row[2] is not None else "",
            "atc_adi":     str(row[3]).strip() if row[3] is not None else "",
            "firma_adi":   str(row[4]).strip() if row[4] is not None else "",
            "recete_turu": str(row[5]).strip() if row[5] is not None else "",
            "durumu":      durumu,
            "language":    "tr",
        })
    return rows_out


@register
class TitckDrugsSource(_HttpMixin, Source):
    name = "titck_drugs"
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
        import io
        import urllib3
        import openpyxl
        from bs4 import BeautifulSoup

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.throttle.wait()
        r = self.session().get(LISTING_URL, timeout=60, verify=False)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.select('a[href$=".xlsx"]')
        if not links:
            raise RuntimeError("[titck] no XLSX links found on listing page")

        href = links[0]["href"]
        if not href.startswith("http"):
            href = "https://www.titck.gov.tr" + href

        self.throttle.wait()
        r2 = self.session().get(href, timeout=120, verify=False)
        r2.raise_for_status()

        wb = openpyxl.load_workbook(io.BytesIO(r2.content), read_only=True, data_only=True)
        ws = wb.active
        rows = _parse_workbook(ws)
        wb.close()

        return rows, None


if __name__ == "__main__":
    raise SystemExit(run_cli(TitckDrugsSource))
