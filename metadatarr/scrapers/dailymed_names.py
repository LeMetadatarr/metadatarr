"""DailyMed drug name scraper (NIH).

Drug names (brand + generic) from the FDA Structured Product Label database.
Richer than openFDA: includes OTC, biologics, animal drugs, and homeopathics.
Also fetches full SPL records for title + setid cross-reference.

Schema per row:
  name_type (G=generic / B=brand, or "SPL"), drug_name,
  setid / published_date (SPL rows only), source

Two page-numbered phases (``drugnames.json`` then ``spls.json``), each
terminating on its own ``metadata.total_pages`` rather than a short page, so
:meth:`fetch` is overridden directly. The cursor is
``{"stage": "names"|"spls", "page": P}``.

NOTE — deviation: the original scraper has no id-based dedup at all (no
``ID_FIELD``, no ``seen`` set — it relies purely on page-checkpoint resume to
avoid re-fetching completed pages). This port sets ``id_field = ""`` to match
that: rows are never dropped for looking like duplicates.

Run it::

    python -m metadatarr.scrapers dailymed_names [--output DIR] [--delay SECS]
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
PAGE = 100


@register
class DailyMedNamesSource(PaginatedJSONSource):
    name = "dailymed_names"
    id_field = ""  # original has no dedup key — page-checkpoint resume only
    default_delay = 0.3

    user_agent = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
    accept = "application/json"

    def session(self):
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

    def initial_cursor(self) -> Dict[str, Any]:
        return {"stage": "names", "page": 1}

    def _get_names_page(self, page: int) -> dict:
        self.throttle.wait()
        r = self.session().get(f"{BASE}/drugnames.json", params={"pagesize": PAGE, "page": page}, timeout=30)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()

    def _get_spls_page(self, page: int) -> dict:
        self.throttle.wait()
        r = self.session().get(f"{BASE}/spls.json", params={"pagesize": PAGE, "page": page}, timeout=30)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()

    def fetch(self, cursor: Dict[str, Any]):
        stage = cursor.get("stage", "names")

        if stage == "names":
            page = int(cursor.get("page", 1))
            data = self._get_names_page(page)
            items = (data.get("data") or []) if data else []

            rows = [
                {"name_type": d.get("name_type", ""), "drug_name": d.get("drug_name", ""),
                 "source": "drugnames"}
                for d in items if d.get("drug_name")
            ]

            total_pages = (data.get("metadata", {}) or {}).get("total_pages", 1) if data else 1
            if not data or not items or page >= total_pages:
                next_cursor = {"stage": "spls", "page": 1}
            else:
                next_cursor = {"stage": "names", "page": page + 1}
            return rows, next_cursor

        if stage == "spls":
            page = int(cursor.get("page", 1))
            data = self._get_spls_page(page)
            items = (data.get("data") or []) if data else []

            rows = [
                {"name_type": "SPL", "drug_name": d.get("title", ""),
                 "setid": d.get("setid", ""), "published_date": d.get("published_date", ""),
                 "source": "spls"}
                for d in items if d.get("title")
            ]

            total_pages = (data.get("metadata", {}) or {}).get("total_pages", 1) if data else 1
            if not data or not items or page >= total_pages:
                next_cursor = None
            else:
                next_cursor = {"stage": "spls", "page": page + 1}
            return rows, next_cursor

        return [], None


if __name__ == "__main__":
    raise SystemExit(run_cli(DailyMedNamesSource))
