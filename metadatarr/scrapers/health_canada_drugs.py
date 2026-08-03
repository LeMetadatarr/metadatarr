"""Health Canada Drug Product Database scraper.

Bilingual (English/French) drug product catalog — the only public drug
database with systematic French brand names and Canadian-market products.

Downloads the official Health Canada bulk data extract ZIP (``allfiles.zip``,
trying several mirror URLs and falling back to the Wayback Machine), then
parses the flat TSV tables inside it. This is a single bulk download + parse,
not an offset-paginated listing, so it is modelled as one page: :meth:`fetch`
downloads and parses everything and returns ``(all_rows, None)``.

  https://www.canada.ca/en/health-canada/services/drugs-health-products/
  drug-products/drug-product-database/read-file-drug-product-database-data-extract.html

Schema per row:
  drug_code, drug_identification_number, brand_name, descriptor, class_name,
  company_name, number_of_ais, last_update_date, status,
  active_ingredients[]{ingredient_name, ingredient_name_f, strength,
                        strength_unit, dosage_form}

Run it::

    python -m metadatarr.scrapers health_canada_drugs [--output DIR]
"""
from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from metadatarr.scrapers.engine import Source, register, run_cli

# Official bulk extract URLs — try in order
_ZIP_URLS = [
    # Primary
    "https://www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles.zip",
    # Legacy path
    "https://www.canada.ca/content/dam/hc-sc/migration/hc-sc/dhp-mps/alt_formats/zip/prodpharma/databasdon/dpd_data_extract.zip",
    # Direct API host
    "https://health-products.canada.ca/dpd-bdpp/api/allfiles.zip",
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"}

# Column layouts from Health Canada data extract documentation
_DRUG_COLS = [
    "drug_code", "product_categorization", "class_e", "drug_identification_number",
    "brand_name", "descriptor", "pediatric_flag", "accession_number", "number_of_ais",
    "last_update_date", "ai_group_no", "company_code", "company_name", "company_type",
    "address_mailing_flag", "suite_number", "street_name", "city_name", "province",
    "country", "postal_code", "post_office_box",
]
_ING_COLS = [
    "drug_code", "active_ingredient_code", "ingredient", "ingredient_supplied_ind",
    "strength", "strength_unit", "strength_type", "dosage_value", "base", "dosage_unit",
    "notes", "ingredient_f", "strength_unit_f", "dosage_unit_f", "notes_f",
]
_STATUS_COLS = ["drug_code", "current_status_flag", "status", "history_date", "lot_number"]


def _try_download(url: str, zip_path: Path) -> bool:
    import requests
    try:
        s = requests.Session()
        s.headers.update(_HEADERS)
        with s.get(url, timeout=300, stream=True) as r:
            if r.status_code != 200:
                return False
            ct = r.headers.get("content-type", "")
            if "html" in ct.lower():
                return False
            downloaded = 0
            tmp = zip_path.with_suffix(".tmp")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    fh.write(chunk)
                    downloaded += len(chunk)
            if downloaded < 100_000:
                tmp.unlink(missing_ok=True)
                return False
            tmp.rename(zip_path)
            return True
    except Exception:
        return False


def _download_zip(output_dir: Path) -> Path:
    zip_path = output_dir / "_health_canada_allfiles.zip"
    if zip_path.exists() and zip_path.stat().st_size > 1_000_000:
        return zip_path

    for url in _ZIP_URLS:
        if _try_download(url, zip_path):
            return zip_path

    # Wayback Machine: find the latest snapshot URL then download it
    import requests
    try:
        cdx = requests.get(
            "http://web.archive.org/cdx/search/cdx",
            params={
                "url": "www.canada.ca/content/dam/hc-sc/documents/services/drug-product-database/allfiles.zip",
                "output": "json", "limit": 1, "fl": "timestamp,original",
                "filter": "statuscode:200", "from": "20230101",
            },
            timeout=20,
        ).json()
        if len(cdx) > 1:
            ts, orig = cdx[1]
            wb_url = f"https://web.archive.org/web/{ts}if_/{orig}"
            if _try_download(wb_url, zip_path):
                return zip_path
    except Exception:
        pass

    raise RuntimeError(
        "Cannot reach Health Canada DPD. The site may be geo-blocking this IP. "
        "Download allfiles.zip manually from "
        "https://www.canada.ca/en/health-canada/services/drugs-health-products/"
        "drug-products/drug-product-database/read-file-drug-product-database-data-extract.html "
        f"and place it at {zip_path}"
    )


def _read_tsv(zf: zipfile.ZipFile, name: str) -> List[list]:
    """Read a quoted-CSV file from the zip (no header row, latin-1 encoded)."""
    try:
        with zf.open(name) as f:
            content = f.read().decode("latin-1")
        reader = csv.reader(io.StringIO(content))
        return [row for row in reader if row]
    except KeyError:
        return []


@register
class HealthCanadaDrugsSource(Source):
    name = "health_canada_drugs"
    id_field = "drug_code"
    default_delay = 0.0

    def initial_cursor(self) -> int:
        return 0


    def fetch(self, cursor: int):
        if cursor is None:
            return [], None

        output_dir = getattr(self, "_output_dir", None)
        if output_dir is None:
            from metadatarr.scrapers._checkpoint import default_output_dir
            output_dir = default_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)

        zip_path = _download_zip(output_dir)

        with zipfile.ZipFile(zip_path) as zf:
            drug_rows = _read_tsv(zf, "drug.txt") or _read_tsv(zf, "bdrug.txt")
            ing_rows = _read_tsv(zf, "ingred.txt") or _read_tsv(zf, "bingred.txt")
            status_rows = _read_tsv(zf, "status.txt") or _read_tsv(zf, "bstatus.txt")

        # Build drug_code -> [ingredients] index
        ing_index: Dict[str, List[dict]] = defaultdict(list)
        for row in ing_rows:
            if len(row) < len(_ING_COLS):
                row = row + [""] * (len(_ING_COLS) - len(row))
            rec = dict(zip(_ING_COLS, row))
            dc = rec.get("drug_code", "").strip()
            if dc:
                ing_index[dc].append({
                    "ingredient_name": rec.get("ingredient", "").strip(),
                    "ingredient_name_f": rec.get("ingredient_f", "").strip(),
                    "strength": rec.get("strength", "").strip(),
                    "strength_unit": rec.get("strength_unit", "").strip(),
                    "dosage_form": rec.get("dosage_unit", "").strip(),
                })

        # Build drug_code -> latest status
        status_index: Dict[str, str] = {}
        for row in status_rows:
            if len(row) < 3:
                continue
            dc = row[0].strip()
            st = row[2].strip() if len(row) > 2 else ""
            status_index[dc] = st  # last seen = latest (file is sorted by history_date)

        rows: List[dict] = []
        seen_ids: set = set()
        for row in drug_rows:
            if len(row) < len(_DRUG_COLS):
                row = row + [""] * (len(_DRUG_COLS) - len(row))
            rec = dict(zip(_DRUG_COLS, row))
            dc = rec.get("drug_code", "").strip()
            if not dc or dc in seen_ids:
                continue
            seen_ids.add(dc)

            rows.append({
                "drug_code": dc,
                "drug_identification_number": rec.get("drug_identification_number", "").strip(),
                "brand_name": rec.get("brand_name", "").strip(),
                "descriptor": rec.get("descriptor", "").strip(),
                "class_name": rec.get("class_e", "").strip(),
                "company_name": rec.get("company_name", "").strip(),
                "number_of_ais": rec.get("number_of_ais", "").strip(),
                "last_update_date": rec.get("last_update_date", "").strip(),
                "status": status_index.get(dc, ""),
                "active_ingredients": ing_index.get(dc, []),
            })

        return rows, None


if __name__ == "__main__":
    raise SystemExit(run_cli(HealthCanadaDrugsSource))
