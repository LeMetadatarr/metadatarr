"""PubChem Compound bulk crawler.

Uses NIH Entrez eutils to page through all compound CIDs, then fetches
property bundles from PubChem PUG REST in batches of 100.

Schema per row:
  cid, iupac_name, molecular_formula, molecular_weight, canonical_smiles,
  inchi, inchikey, charge, xlogp, exact_mass, synonyms (first 20)

Pagination is a two-tier fetch (10k-CID esearch page, then 100-CID property
batches within it) driven by a total-CID count from Entrez, which doesn't fit
the engine's offset/skip model, so :meth:`fetch` is overridden directly. The
cursor is the plain ``retstart`` int Entrez esearch uses.

Run it::

    python -m metadatarr.scrapers pubchem [--output DIR] [--delay SECS] [--limit N]
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
BATCH = 100
SEARCH_PAGE_SIZE = 10_000

_PROPERTIES = ",".join([
    "IUPACName", "MolecularFormula", "MolecularWeight",
    "CanonicalSMILES", "InChI", "InChIKey", "Charge", "XLogP", "ExactMass",
])


@register
class PubChemCompoundsSource(PaginatedJSONSource):
    name = "pubchem_compounds"
    id_field = "cid"
    default_delay = 0.34  # ~3 req/s, well under limits

    accept = "application/json"

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self._total_cids_cache: Optional[int] = None

    def session(self):
        if self._session is None:
            try:
                from unblock_requests import CloudflareSession
                s = CloudflareSession()
            except Exception:
                import requests
                s = requests.Session()
            s.headers.update({"Accept": self.accept})
            self._session = s
        return self._session

    def initial_cursor(self) -> int:
        return 0

    def _get(self, url: str, **params) -> dict:
        self.throttle.wait()
        r = self.session().get(url, params=params or None, timeout=30)
        r.raise_for_status()
        return r.json()

    def _search_cids(self, retstart: int, retmax: int = SEARCH_PAGE_SIZE) -> List[int]:
        try:
            data = self._get(f"{EUTILS}/esearch.fcgi",
                             db="pccompound", term="0:999999999[CID]",
                             retmax=retmax, retstart=retstart, retmode="json")
            ids = data.get("esearchresult", {}).get("idlist", [])
            return [int(x) for x in ids]
        except Exception:
            return []

    def _total_cids(self) -> int:
        if self._total_cids_cache is not None:
            return self._total_cids_cache
        try:
            data = self._get(f"{EUTILS}/esearch.fcgi",
                             db="pccompound", term="0:999999999[CID]", retmax=0, retmode="json")
            total = int(data.get("esearchresult", {}).get("count", 0))
        except Exception:
            total = 0
        self._total_cids_cache = total
        return total

    def _fetch_properties(self, cids: List[int]) -> dict:
        try:
            cid_str = ",".join(map(str, cids))
            data = self._get(f"{PUG}/compound/cid/{cid_str}/property/{_PROPERTIES}/JSON")
            return {
                str(p["CID"]): p
                for p in data.get("PropertyTable", {}).get("Properties", [])
            }
        except Exception:
            return {}

    def _fetch_synonyms(self, cids: List[int]) -> dict:
        try:
            cid_str = ",".join(map(str, cids))
            data = self._get(f"{PUG}/compound/cid/{cid_str}/synonyms/JSON")
            result = {}
            for item in data.get("InformationList", {}).get("Information", []):
                cid = str(item.get("CID", ""))
                result[cid] = item.get("Synonym", [])[:20]
            return result
        except Exception:
            return {}

    def map_row(self, cid: int, props: dict, syns: List[str]) -> Dict[str, Any]:
        return {
            "cid": cid,
            "iupac_name": props.get("IUPACName", ""),
            "molecular_formula": props.get("MolecularFormula", ""),
            "molecular_weight": props.get("MolecularWeight"),
            "canonical_smiles": props.get("CanonicalSMILES", ""),
            "inchi": props.get("InChI", ""),
            "inchikey": props.get("InChIKey", ""),
            "charge": props.get("Charge"),
            "xlogp": props.get("XLogP"),
            "exact_mass": props.get("ExactMass"),
            "synonyms": syns,
        }

    def fetch(self, cursor: int):
        retstart = int(cursor or 0)
        total_cids = self._total_cids()

        if retstart != 0 and retstart >= total_cids:
            return [], None

        batch_cids = self._search_cids(retstart, SEARCH_PAGE_SIZE)
        if not batch_cids:
            return [], None

        already = getattr(self, "_seen", set()) or set()
        new_cids = [c for c in batch_cids if str(c) not in already]

        rows: List[Dict[str, Any]] = []
        for i in range(0, len(new_cids), BATCH):
            chunk = new_cids[i:i + BATCH]
            props_map = self._fetch_properties(chunk)
            syns_map = self._fetch_synonyms(chunk)
            rows.extend(
                self.map_row(c, props_map.get(str(c), {}), syns_map.get(str(c), []))
                for c in chunk
            )

        next_retstart = retstart + len(batch_cids)
        next_cursor = None if next_retstart >= total_cids else next_retstart
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(PubChemCompoundsSource))
