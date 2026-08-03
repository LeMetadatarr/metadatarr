"""ChEMBL molecule synonym scraper.

Fetches all ChEMBL molecules that have synonyms and extracts their typed name
variants — the most comprehensive international drug name database available
without authentication.

Synonym types captured: INN, INN_SPANISH, INN_FRENCH, USAN, BAN, JAN, ATC,
TRADE_NAME, RESEARCH_CODE, OTHER / MERCK_INDEX / ...

Schema per row:
  chembl_id, pref_name, max_phase, molecule_type, first_approval,
  atc_classifications[], usan_stem, usan_stem_definition, oral, parenteral,
  topical, withdrawn_flag, black_box_warning,
  synonyms[]{name, syn_type, language}, pubchem_cid, inchi, canonical_smiles

The end signal is ChEMBL's own ``page_meta.total_count`` rather than a
short-page check, so :meth:`fetch` is overridden directly to match exactly.

Run it::

    python -m metadatarr.scrapers chembl_drugs [--output DIR] [--delay SECS]
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

BASE = "https://www.ebi.ac.uk/chembl/api/data/molecule.json"
PAGE = 100

_SYN_LANGUAGE = {
    "INN": "en",
    "INN_SPANISH": "es",
    "INN_FRENCH": "fr",
    "INN_GERMAN": "de",
    "INN_LATIN": "la",
    "INN_PORTUGUESE": "pt",
    "INN_JAPANESE": "ja",
    "JAN": "ja",
    "USAN": "en",
    "BAN": "en",
    "ATC": "en",
    "TRADE_NAME": "",
    "OTHER": "",
    "RESEARCH_CODE": "",
}


def _syn_language(syn_type: str) -> str:
    """Infer language from syn_type."""
    return _SYN_LANGUAGE.get(syn_type, "")


def _pubchem_cid(cross_refs: list) -> Optional[int]:
    for ref in cross_refs:
        if ref.get("xref_src") == "PubChem":
            try:
                return int(ref.get("xref_id", 0))
            except (ValueError, TypeError):
                pass
    return None


@register
class ChemblDrugsSource(PaginatedJSONSource):
    name = "chembl_drugs"
    id_field = "chembl_id"
    default_delay = 0.3

    base = BASE
    results_key = "molecules"
    page_size = PAGE
    accept = "application/json"

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
                "Accept": self.accept,
            })
            self._session = s
        return self._session

    def initial_cursor(self) -> int:
        return 0

    def _get_page(self, offset: int) -> dict:
        self.throttle.wait()
        params = {
            "molecule_synonyms__isnull": "false",
            "limit": PAGE,
            "offset": offset,
        }
        r = self.session().get(self.base, params=params, timeout=30)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()

    def map_row(self, mol: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        structs = mol.get("molecule_structures") or {}
        syns = mol.get("molecule_synonyms") or []
        cross_refs = mol.get("cross_references") or []
        return {
            "chembl_id": mol.get("molecule_chembl_id", ""),
            "pref_name": mol.get("pref_name", "") or "",
            "max_phase": mol.get("max_phase"),
            "molecule_type": mol.get("molecule_type", ""),
            "first_approval": mol.get("first_approval"),
            "atc_classifications": mol.get("atc_classifications") or [],
            "usan_stem": mol.get("usan_stem") or "",
            "usan_stem_definition": mol.get("usan_stem_definition") or "",
            "oral": mol.get("oral", False),
            "parenteral": mol.get("parenteral", False),
            "topical": mol.get("topical", False),
            "withdrawn_flag": mol.get("withdrawn_flag", False),
            "black_box_warning": mol.get("black_box_warning", False),
            "synonyms": [
                {
                    "name": s.get("synonyms", ""),
                    "syn_type": s.get("syn_type", ""),
                    "language": _syn_language(s.get("syn_type", "")),
                }
                for s in syns if s.get("synonyms")
            ],
            "pubchem_cid": _pubchem_cid(cross_refs),
            "inchi": structs.get("standard_inchi", ""),
            "canonical_smiles": structs.get("canonical_smiles", ""),
        }

    def fetch(self, cursor: int):
        offset = int(cursor or 0)
        data = self._get_page(offset)
        if not data:
            return [], None
        molecules: List[Dict[str, Any]] = data.get("molecules") or []
        if not molecules:
            return [], None

        rows = [self.map_row(m) for m in molecules]

        next_offset = offset + len(molecules)
        page_total = data.get("page_meta", {}).get("total_count", 0)
        next_cursor = None if next_offset >= page_total else next_offset
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(ChemblDrugsSource))
