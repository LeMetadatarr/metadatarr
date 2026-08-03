"""CBG-MEB (Netherlands) drug product scraper — migrated onto the engine.

Dutch national drug registry — Dutch-language brand names, active
ingredients, ATC codes, dispensing status. Single bulk pipe-delimited CSV
download + parse, so it is modelled as one page: :meth:`fetch` downloads and
parses the whole file and returns ``(all_rows, None)`` on cursor 0. Rows with
an empty ``PRODUCTNAAM`` are dropped, exactly as in the original.

The original never deduplicated rows, so ``id_field`` is left empty.

Schema per row:
  registratienummer, productnaam, inschrijvingsdatum, handelsvergunninghouder,
  afleverstatus, farmaceutischevorm, atc, werkzamestoffen, language

TLS verification is disabled, matching the original's ``verify=False`` +
``urllib3.disable_warnings``.

Run it::

    python -m metadatarr.scrapers cbg_drugs [--output DIR]
"""
from __future__ import annotations

import csv
import io
from typing import List

import requests

from metadatarr.scrapers.engine import Page, Source, register, run_cli

CSV_URL = "https://www.geneesmiddeleninformatiebank.nl/metadata.csv"


@register
class CbgDrugsSource(Source):
    name = "cbg_drugs"
    id_field = ""
    default_delay = 0.0

    def initial_cursor(self) -> int:
        return 0

    def fetch(self, cursor: int) -> Page:
        if cursor is None:
            return [], None

        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        s = requests.Session()
        s.headers["User-Agent"] = (
            "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
        )
        r = s.get(CSV_URL, timeout=120, verify=False, stream=True)
        r.raise_for_status()

        raw = b""
        for chunk in r.iter_content(65536):
            raw += chunk
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")

        reader = csv.DictReader(io.StringIO(text), delimiter="|")
        rows: List[dict] = []
        for item in reader:
            clean = {k.strip().lstrip("﻿"): (v or "").strip() for k, v in item.items() if k}
            productnaam = clean.get("PRODUCTNAAM", "")
            if not productnaam:
                continue
            rows.append({
                "registratienummer": clean.get("REGISTRATIENUMMER", ""),
                "productnaam": productnaam,
                "inschrijvingsdatum": clean.get("INSCHRIJVINGSDATUM", ""),
                "handelsvergunninghouder": clean.get("HANDELSVERGUNNINGHOUDER", ""),
                "afleverstatus": clean.get("AFLEVERSTATUS", ""),
                "farmaceutischevorm": clean.get("FARMACEUTISCHEVORM", ""),
                "atc": clean.get("ATC", ""),
                "werkzamestoffen": clean.get("WERKZAMESTOFFEN", ""),
                "language": "nl",
            })

        return rows, None


if __name__ == "__main__":
    raise SystemExit(run_cli(CbgDrugsSource))
