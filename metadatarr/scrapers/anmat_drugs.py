"""ANMAT (Argentina) drug product scraper.

Argentine Vademecum Nacional de Medicamentos — Spanish-language brand/generic
names, laboratory, concentration, form, presentation. Discovers CSV resources
via the CKAN dataset-search API on datos.salud.gob.ar, downloads and unions
every CSV resource found. This is a single bulk discover + download + parse
pass, not paginated, so it is modelled as one page: :meth:`fetch` returns
``(all_rows, None)``.

Deduplication key is the composite ``(nombre_comercial, nombre_generico,
concentracion)`` (case-insensitive), which the engine's single-field
``id_field`` dedup can't express — kept as manual in-fetch dedup exactly like
the original, with ``id_field=""`` (no engine-level dedup needed for a
single-shot harvest).

Schema per row:
  nombre_comercial, nombre_generico, laboratorio_titular, concentracion,
  forma_farmaceutica, presentacion, numero_certificado, language, source_url

Run it::

    python -m metadatarr.scrapers anmat_drugs [--output DIR]
"""
from __future__ import annotations

import csv
import io

from metadatarr.scrapers.engine import Source, register, run_cli

API_URL = (
    "https://datos.salud.gob.ar/api/3/action/package_search"
    "?q=Vademecun+Nacional+de+Medicamentos&rows=3"
)


@register
class AnmatDrugsSource(Source):
    name = "anmat_drugs"
    id_field = ""
    default_delay = 0.0

    def initial_cursor(self) -> int:
        return 0

    def map_row(self, clean: dict, csv_url: str) -> dict:
        return {
            "nombre_comercial":    clean.get("nombre_comercial", ""),
            "nombre_generico":     clean.get("nombre_generico", ""),
            "laboratorio_titular": clean.get("laboratorio_titular", ""),
            "concentracion":       clean.get("concentracion", ""),
            "forma_farmaceutica":  clean.get("forma_farmaceutica", ""),
            "presentacion":        clean.get("presentacion", ""),
            "numero_certificado":  clean.get("numero_certificado", ""),
            "language":            "es-AR",
            "source_url":          csv_url,
        }

    def fetch(self, cursor: int):
        if cursor is None:
            return [], None

        import urllib3
        import requests as _requests

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        s = _requests.Session()
        s.headers["User-Agent"] = (
            "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
        )

        # --- 1. Discover CSV resource URLs via CKAN API ---
        r = s.get(API_URL, timeout=60, verify=False)
        r.raise_for_status()
        data = r.json()

        csv_urls = []
        results = data.get("result", {}).get("results", [])
        for pkg in results:
            for res in pkg.get("resources", []):
                fmt = res.get("format", "").upper()
                url = res.get("url", "")
                if fmt == "CSV" and url:
                    csv_urls.append(url)

        if not csv_urls:
            raise RuntimeError("[anmat] no CSV resources found in API response")

        # --- 2. Download and parse each CSV, dedup in memory ---
        seen: set = set()
        rows_out = []

        for csv_url in csv_urls:
            try:
                r2 = s.get(csv_url, timeout=120, verify=False)
                r2.raise_for_status()
            except Exception:
                continue

            raw = r2.content

            for enc in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                continue

            # Auto-detect delimiter (semicolon or comma)
            first_line = text.split("\n", 1)[0]
            delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","

            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            for item in reader:
                clean = {k.strip().lstrip("﻿"): v.strip() for k, v in item.items() if k}

                dedup_key = (
                    clean.get("nombre_comercial", "").lower(),
                    clean.get("nombre_generico", "").lower(),
                    clean.get("concentracion", "").lower(),
                )
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                rows_out.append(self.map_row(clean, csv_url))

        return rows_out, None


if __name__ == "__main__":
    raise SystemExit(run_cli(AnmatDrugsSource))
