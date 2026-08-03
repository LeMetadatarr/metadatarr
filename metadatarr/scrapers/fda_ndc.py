"""FDA NDC (National Drug Code) directory scraper — migrated onto the engine.

136k+ registered drug products with brand name, generic name, active
ingredients, strength, dosage form, route, and packaging descriptions.
Downloads the bulk ZIP (no rate limits), cached to
``{output_dir}/_fda_ndc.zip``, and parses the tab-delimited ``product.txt``
inside it. Single bulk download + parse, so it is modelled as one page:
:meth:`fetch` downloads and parses the whole file and returns
``(all_rows, None)`` on cursor 0.

The original never deduplicated rows, so ``id_field`` is left empty.

Schema per row:
  product_ndc, generic_name, brand_name, brand_name_suffix, labeler_name,
  product_type, dosage_form, route[], marketing_category,
  application_number, substance_name, active_numerator_strength,
  active_ingred_unit, pharm_classes, deaschedule, marketing_start_date,
  marketing_end_date, listing_record_certified_through

Run it::

    python -m metadatarr.scrapers fda_ndc [--output DIR]
"""
from __future__ import annotations

import csv
import io
import zipfile
from typing import List

from metadatarr.scrapers.engine import Page, Source, register, run_cli

ZIP_URL = "https://www.accessdata.fda.gov/cder/ndctext.zip"
PRODUCT_FILE = "product.txt"


def _row(r: dict) -> dict:
    return {
        "product_ndc": r.get("PRODUCTNDC", ""),
        "generic_name": r.get("NONPROPRIETARYNAME", ""),
        "brand_name": r.get("PROPRIETARYNAME", ""),
        "brand_name_suffix": r.get("PROPRIETARYNAMESUFFIX", ""),
        "labeler_name": r.get("LABELERNAME", ""),
        "product_type": r.get("PRODUCTTYPENAME", ""),
        "dosage_form": r.get("DOSAGEFORMNAME", ""),
        "route": [r.get("ROUTENAME", "")] if r.get("ROUTENAME") else [],
        "marketing_category": r.get("MARKETINGCATEGORYNAME", ""),
        "application_number": r.get("APPLICATIONNUMBER", ""),
        "substance_name": r.get("SUBSTANCENAME", ""),
        "active_numerator_strength": r.get("ACTIVE_NUMERATOR_STRENGTH", ""),
        "active_ingred_unit": r.get("ACTIVE_INGRED_UNIT", ""),
        "pharm_classes": r.get("PHARM_CLASSES", ""),
        "deaschedule": r.get("DEASCHEDULE", ""),
        "marketing_start_date": r.get("MARKETINGSTART", ""),
        "marketing_end_date": r.get("MARKETINGEND", ""),
        "listing_record_certified_through": r.get("LISTING_RECORD_CERTIFIED_THROUGH", ""),
    }


@register
class FdaNdcSource(Source):
    name = "fda_ndc"
    id_field = ""
    default_delay = 0.0

    def initial_cursor(self) -> int:
        return 0

    def fetch(self, cursor: int) -> Page:
        if cursor is None:
            return [], None

        import requests

        output_dir = self._output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        cache_zip = output_dir / "_fda_ndc.zip"

        if not cache_zip.exists():
            s = requests.Session()
            s.headers["User-Agent"] = "Mozilla/5.0"
            r = s.get(ZIP_URL, timeout=120)
            r.raise_for_status()
            cache_zip.write_bytes(r.content)

        with zipfile.ZipFile(cache_zip) as z:
            with z.open(PRODUCT_FILE) as f:
                text = f.read().decode("utf-8", errors="replace")

        reader = csv.DictReader(io.StringIO(text), delimiter="\t")
        rows: List[dict] = [_row(item) for item in reader]

        return rows, None


if __name__ == "__main__":
    raise SystemExit(run_cli(FdaNdcSource))
