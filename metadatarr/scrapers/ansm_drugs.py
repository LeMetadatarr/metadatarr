"""ANSM (France) drug specialities scraper — migrated onto the engine.

Downloads two tab-separated files from the French public drug database
(base-donnees-publique.medicaments.gouv.fr): the composition file (substance
list per CIS code) and the speciality list, joins them on CIS code, and
emits one row per speciality with a nested substance list.

Single bulk download + parse, not offset-paginated, so it is modelled as one
page: :meth:`fetch` downloads and parses both files and returns
``(all_rows, None)`` on cursor 0, mirroring ``who_atc``/``titck_drugs``.

The original never deduplicated rows (each CIS code appears once in the
speciality file), so ``id_field`` is left empty — matching the engine's "no
identity, keep everything" behaviour.

Schema per row:
  cis_code, specialite_name, dosage_form, route, status,
  commercialisation_status, holders, substances[]{code, name, dosage},
  language, source

TLS verification is disabled, matching the original's ``verify=False`` +
``urllib3.disable_warnings``.

Run it::

    python -m metadatarr.scrapers ansm_drugs [--output DIR]
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from typing import Dict, List

import requests

from metadatarr.scrapers.engine import Page, Source, register, run_cli

SPECIALITES_URL = (
    "https://base-donnees-publique.medicaments.gouv.fr/download/file/CIS_bdpm.txt"
)
COMPO_URL = (
    "https://base-donnees-publique.medicaments.gouv.fr/download/file/CIS_COMPO_bdpm.txt"
)


def _download(session, url: str) -> str:
    """Download URL, return decoded text (UTF-8 then latin-1 fallback)."""
    r = session.get(url, timeout=120, verify=False)
    r.raise_for_status()
    raw = r.content
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


@register
class AnsmDrugsSource(Source):
    name = "ansm_drugs"
    id_field = ""
    default_delay = 0.0

    def initial_cursor(self) -> int:
        return 0

    def fetch(self, cursor: int) -> Page:
        if cursor is None:
            return [], None

        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        session = requests.Session()
        session.headers["User-Agent"] = (
            "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
        )

        # Phase 1: composition file — build substance lookup by CIS code.
        compo_text = _download(session, COMPO_URL)
        substances: Dict[str, List[dict]] = defaultdict(list)
        reader = csv.reader(io.StringIO(compo_text), delimiter="\t")
        for row in reader:
            if len(row) < 4:
                continue
            cis = row[0].strip()
            substances[cis].append({
                "code": row[2].strip() if len(row) > 2 else "",
                "name": row[3].strip() if len(row) > 3 else "",
                "dosage": row[4].strip() if len(row) > 4 else "",
            })

        # Phase 2: speciality list.
        spec_text = _download(session, SPECIALITES_URL)
        rows: List[dict] = []
        reader = csv.reader(io.StringIO(spec_text), delimiter="\t")
        for row in reader:
            if len(row) < 2:
                continue
            cis = row[0].strip()
            rows.append({
                "cis_code": cis,
                "specialite_name": row[1].strip() if len(row) > 1 else "",
                "dosage_form": row[2].strip() if len(row) > 2 else "",
                "route": row[3].strip() if len(row) > 3 else "",
                "status": row[4].strip() if len(row) > 4 else "",
                "commercialisation_status": row[6].strip() if len(row) > 6 else "",
                "holders": row[10].strip() if len(row) > 10 else "",
                "substances": substances.get(cis, []),
                "language": "fr",
                "source": "ansm",
            })

        return rows, None


if __name__ == "__main__":
    raise SystemExit(run_cli(AnsmDrugsSource))
