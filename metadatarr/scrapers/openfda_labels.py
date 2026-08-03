"""openFDA drug-label bulk crawler.

Harvests FDA drug-label records from the openFDA API (no key; ~240 req/min).
The API caps ``skip`` at 25k, so records are harvested in per-year
``effective_time`` partitions (plus a catch-all for undated records), each
walked by offset. Resumable and deduplicated by ``set_id``.

Run it::

    python -m metadatarr.scrapers openfda_labels [--output DIR] [--delay SECS] [--limit N]
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PartitionedJSONSource, register, run_cli


def _first(val) -> str:
    if isinstance(val, list):
        return val[0] if val else ""
    return val or ""


def _join(val) -> str:
    if isinstance(val, list):
        return " ".join(val)
    return val or ""


@register
class OpenFDALabels(PartitionedJSONSource):
    name = "openfda_labels"
    id_field = "set_id"
    default_delay = 0.26  # ~230 req/min, under the 240 cap

    base = "https://api.fda.gov/drug/label.json"
    results_key = "results"
    page_size = 100
    skip_param = "skip"
    limit_param = "limit"

    def session(self):
        # openFDA sits behind Cloudflare-style protection intermittently; use
        # the unblock_requests session when available, else a plain one.
        if self._session is None:
            try:
                from unblock_requests import CloudflareSession
                s = CloudflareSession()
            except Exception:
                import requests
                s = requests.Session()
            s.headers.update({"User-Agent": self.user_agent, "Accept": self.accept})
            self._session = s
        return self._session

    def partitions(self) -> List[Dict[str, Any]]:
        parts = [{"search": f"effective_time:[{year}0101+TO+{year}1231]"}
                 for year in range(1950, 2030)]
        parts.append({"search": "_missing_:effective_time"})
        return parts

    def map_row(self, r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        openfda = r.get("openfda") or {}
        return {
            "set_id": r.get("set_id", ""),
            "id": r.get("id", ""),
            "effective_time": r.get("effective_time", ""),
            "brand_name": _first(openfda.get("brand_name")),
            "generic_name": _first(openfda.get("generic_name")),
            "manufacturer_name": _first(openfda.get("manufacturer_name")),
            "product_type": _first(openfda.get("product_type")),
            "route": openfda.get("route") or [],
            "substance_name": openfda.get("substance_name") or [],
            "application_number": openfda.get("application_number") or [],
            "rxcui": openfda.get("rxcui") or [],
            "ndc": openfda.get("package_ndc") or [],
            "spl_id": openfda.get("spl_id") or [],
            "indications_and_usage": _join(r.get("indications_and_usage")),
            "warnings": _join(r.get("warnings")),
            "boxed_warning": _join(r.get("boxed_warning")),
            "dosage_and_administration": _join(r.get("dosage_and_administration")),
            "drug_interactions": _join(r.get("drug_interactions")),
            "adverse_reactions": _join(r.get("adverse_reactions")),
            "description": _join(r.get("description")),
            "active_ingredient": _join(r.get("active_ingredient")),
            "inactive_ingredient": _join(r.get("inactive_ingredient")),
        }


if __name__ == "__main__":
    raise SystemExit(run_cli(OpenFDALabels))
