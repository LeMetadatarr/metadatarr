"""EMA European Public Assessment Report (EPAR) scraper — migrated onto the
engine.

Downloads the EMA medicines output Excel file and extracts all authorised
medicine records. Single bulk download + parse, so it is modelled as one
page: :meth:`fetch` downloads and parses the whole workbook and returns
``(all_rows, None)`` on cursor 0.

The workbook has a metadata preamble; the actual column headers begin at the
first row whose first cell contains substantive column-name text (not
"Content type:" or blank). All subsequent rows are data. Column names are
matched by substring against :data:`_COL_MAP` (case-insensitive, first match
wins) since EMA has changed exact header wording across releases.

The original never deduplicated rows, so ``id_field`` is left empty.

Schema per row:
  medicine_name, inn_common_name, active_substance, product_number,
  authorisation_status, atc_code, therapeutic_area, date_of_authorisation,
  generic, orphan, biosimilar, url

Run it::

    python -m metadatarr.scrapers ema_epar [--output DIR]
"""
from __future__ import annotations

import io
from typing import Any, Dict, Iterator, List, Optional

from metadatarr.scrapers.engine import Page, Source, register, run_cli

XLSX_URL = (
    "https://www.ema.europa.eu/en/documents/report/"
    "medicines-output-medicines-report_en.xlsx"
)

# Mapping from possible Excel column header substrings -> schema field names.
# Matching is case-insensitive, first match wins.
_COL_MAP = [
    ("medicine name", "medicine_name"),
    ("inn", "inn_common_name"),
    ("common name", "inn_common_name"),
    ("active substance", "active_substance"),
    ("product number", "product_number"),
    ("authorisation status", "authorisation_status"),
    ("authorisation date", "date_of_authorisation"),
    ("date of authorisation", "date_of_authorisation"),
    ("atc code", "atc_code"),
    ("atc", "atc_code"),
    ("therapeutic area", "therapeutic_area"),
    ("indication", "therapeutic_area"),
    ("generic", "generic"),
    ("orphan", "orphan"),
    ("biosimilar", "biosimilar"),
    ("url", "url"),
    ("product page", "url"),
]

_EMPTY_RECORD = {
    "medicine_name": "",
    "inn_common_name": "",
    "active_substance": "",
    "product_number": "",
    "authorisation_status": "",
    "atc_code": "",
    "therapeutic_area": "",
    "date_of_authorisation": "",
    "generic": "",
    "orphan": "",
    "biosimilar": "",
    "url": "",
}


def _map_column(header: str) -> Optional[str]:
    h = header.lower().strip()
    for keyword, field in _COL_MAP:
        if keyword in h:
            return field
    return None


def _cell_value(cell: Any) -> str:
    v = cell.value
    if v is None:
        return ""
    return str(v).strip()


def _is_header_row(row: tuple) -> bool:
    """Return True if this row looks like a column-header row (not metadata)."""
    first = row[0].value
    if first is None:
        return False
    s = str(first).strip().lower()
    if s.startswith("content type") or s.startswith("date") or not s:
        return False
    non_empty = sum(1 for c in row if c.value is not None)
    return non_empty >= 3


def _parse_xlsx(xlsx_bytes: bytes) -> Iterator[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True, read_only=True)
    ws = wb.active

    header_idx: Optional[int] = None
    col_map: List[Optional[str]] = []

    for row_idx, row in enumerate(ws.iter_rows()):
        if header_idx is None:
            if _is_header_row(row):
                header_idx = row_idx
                col_map = [_map_column(_cell_value(c)) for c in row]
            continue

        values = [_cell_value(c) for c in row]
        if not any(values):
            continue
        record: Dict[str, str] = dict(_EMPTY_RECORD)
        for col_i, field in enumerate(col_map):
            if field and col_i < len(values):
                if not record.get(field):
                    record[field] = values[col_i]
        yield record

    wb.close()


@register
class EmaEparSource(Source):
    name = "ema_epar"
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
                "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, */*",
            })
            self._session = s
        return self._session

    def fetch(self, cursor: int) -> Page:
        if cursor is None:
            return [], None

        r = self.session().get(XLSX_URL, timeout=120, stream=True)
        r.raise_for_status()
        chunks = []
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                chunks.append(chunk)
        xlsx_bytes = b"".join(chunks)

        rows = list(_parse_xlsx(xlsx_bytes))
        return rows, None


if __name__ == "__main__":
    raise SystemExit(run_cli(EmaEparSource))
