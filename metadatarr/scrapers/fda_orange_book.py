"""FDA Orange Book drug product scraper — migrated onto the engine.

Downloads the FDA Orange Book ZIP archive and parses the tilde-delimited
``products.txt`` file inside it. Single bulk download + parse, so it is
modelled as one page: :meth:`fetch` downloads and parses the whole file and
returns ``(all_rows, None)`` on cursor 0.

Header row:
  Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~
  Product_No~TE_Code~Approval_Date~RLD~RS~Type~Applicant_Full_Name

The original never deduplicated rows, so ``id_field`` is left empty.

Schema per row:
  ingredient, dosage_form, route, trade_name, applicant, strength,
  appl_type, appl_no, product_no, te_code, approval_date, rld, rs,
  drug_type, applicant_full_name

~48,381 data rows.

Run it::

    python -m metadatarr.scrapers fda_orange_book [--output DIR]
"""
from __future__ import annotations

import io
import zipfile
from typing import Iterator

from metadatarr.scrapers.engine import Page, Source, register, run_cli

ZIP_URL = "https://www.fda.gov/media/76860/download"
PRODUCTS_FILE = "products.txt"
SEP = "~"
HEADER_PREFIX = "Ingredient"


def _parse_products(zip_bytes: bytes) -> Iterator[dict]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        target = next((n for n in names if n.lower() == PRODUCTS_FILE.lower()), None)
        if target is None:
            target = next((n for n in names if "product" in n.lower()), None)
        if target is None:
            raise RuntimeError(f"Cannot find {PRODUCTS_FILE} in ZIP. Files: {names}")
        with zf.open(target) as fh:
            raw = fh.read().decode("latin-1")

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(HEADER_PREFIX):
            continue  # skip header row(s)
        parts = line.split(SEP)
        if len(parts) < 14:
            parts += [""] * (14 - len(parts))

        df_route = parts[1]
        if ";" in df_route:
            dosage_form, route = df_route.split(";", 1)
        else:
            dosage_form = df_route
            route = ""

        yield {
            "ingredient": parts[0].strip(),
            "dosage_form": dosage_form.strip(),
            "route": route.strip(),
            "trade_name": parts[2].strip(),
            "applicant": parts[3].strip(),
            "strength": parts[4].strip(),
            "appl_type": parts[5].strip(),
            "appl_no": parts[6].strip(),
            "product_no": parts[7].strip(),
            "te_code": parts[8].strip(),
            "approval_date": parts[9].strip(),
            "rld": parts[10].strip(),
            "rs": parts[11].strip(),
            "drug_type": parts[12].strip(),
            "applicant_full_name": parts[13].strip(),
        }


@register
class FdaOrangeBookSource(Source):
    name = "fda_orange_book"
    id_field = ""
    default_delay = 1.0

    def initial_cursor(self) -> int:
        return 0

    def session(self):
        if self._session is None:
            try:
                from unblock_requests import CloudflareSession
                s = CloudflareSession()
            except Exception:
                import requests
                s = requests.Session()
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
                "Accept": "application/zip, application/octet-stream, */*",
            })
            self._session = s
        return self._session

    def fetch(self, cursor: int) -> Page:
        if cursor is None:
            return [], None

        r = self.session().get(ZIP_URL, timeout=120, stream=True)
        r.raise_for_status()
        chunks = []
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                chunks.append(chunk)
        zip_bytes = b"".join(chunks)

        rows = list(_parse_products(zip_bytes))
        return rows, None


if __name__ == "__main__":
    raise SystemExit(run_cli(FdaOrangeBookSource))
