"""DrugBank Open Data crawler — migrated onto the engine.

Downloads and parses the DrugBank Open Data CSV bundle (no API key required
for the open/approved-drugs subset). The direct download requires a (free)
account click-through, so this scraper accepts a pre-downloaded CSV path via
``--csv`` OR attempts the known stable URL with ``unblock_requests`` (which,
in practice, raises with instructions unless the session already carries a
DrugBank account cookie) — exactly like the original.

Single bulk parse, so it is modelled as one page: :meth:`fetch` reads/parses
the whole CSV and returns ``(all_rows, None)`` on cursor 0.

Schema per row:
  drugbank_id, name, cas_number, unii, synonyms[], standard_inchi,
  standard_inchi_key, smiles, formula, groups[], atc_codes[], description,
  indication, pharmacodynamics, mechanism_of_action, food_interactions[],
  categories[]

Run it::

    python -m metadatarr.scrapers drugbank_open --csv /path/to/drugbank_open.csv [--output DIR]
    python -m metadatarr.scrapers drugbank_open [--output DIR]   # attempts direct download
"""
from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path
from typing import Iterator, Optional

from metadatarr.scrapers.engine import Page, Source, register, run_cli

OPEN_CSV_LATEST = "https://go.drugbank.com/releases/latest/downloads/all-open-data-csv"


def _parse_row(row: dict) -> dict:
    return {
        "drugbank_id": row.get("DrugBank ID", ""),
        "name": row.get("Name", ""),
        "cas_number": row.get("CAS Number", ""),
        "unii": row.get("UNII", ""),
        "synonyms": [s.strip() for s in (row.get("Synonyms") or "").split("|") if s.strip()],
        "standard_inchi": row.get("Standard InChI", ""),
        "standard_inchi_key": row.get("Standard InChI Key", ""),
        "smiles": row.get("SMILES", ""),
        "formula": row.get("Formula", ""),
        "groups": [g.strip() for g in (row.get("Groups") or "").split(";") if g.strip()],
        "atc_codes": [a.strip() for a in (row.get("ATC Codes") or "").split("|") if a.strip()],
        "description": row.get("Description", ""),
        "indication": row.get("Indication", ""),
        "pharmacodynamics": row.get("Pharmacodynamics", ""),
        "mechanism_of_action": row.get("Mechanism of Action", ""),
        "food_interactions": [f.strip() for f in (row.get("Food Interactions") or "").split("|") if f.strip()],
        "categories": [c.strip() for c in (row.get("Categories") or "").split(";") if c.strip()],
    }


def _iter_csv(text: str) -> Iterator[dict]:
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        yield _parse_row(row)


@register
class DrugbankOpenSource(Source):
    name = "drugbank_open"
    id_field = "drugbank_id"
    default_delay = 2.0

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self._csv_path: Optional[str] = None
        self._session = None

    @classmethod
    def add_cli_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--csv", default=None,
                             help="Path to pre-downloaded DrugBank open CSV")

    def configure(self, args: argparse.Namespace) -> None:
        self._csv_path = args.csv

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
                "Accept": "text/csv,application/csv,text/plain,*/*",
            })
            self._session = s
        return self._session

    def _download_csv(self) -> str:
        """Attempt to download the open data CSV. Requires a free DrugBank account cookie."""
        self.throttle.wait()
        r = self.session().get(OPEN_CSV_LATEST, timeout=120, allow_redirects=True)
        if r.status_code == 200 and "DrugBank ID" in r.text[:500]:
            return r.text
        raise RuntimeError(
            "DrugBank requires a free account to download.\n"
            "1. Register at https://go.drugbank.com/users/sign_up\n"
            "2. Download the open data CSV from https://go.drugbank.com/releases/latest#open-data\n"
            "3. Run: python -m metadatarr.scrapers drugbank_open --csv /path/to/drugbank_open.csv"
        )

    def fetch(self, cursor: int) -> Page:
        if cursor is None:
            return [], None

        if self._csv_path:
            text = Path(self._csv_path).read_text(encoding="utf-8")
        else:
            text = self._download_csv()

        rows = list(_iter_csv(text))
        return rows, None


if __name__ == "__main__":
    raise SystemExit(run_cli(DrugbankOpenSource))
