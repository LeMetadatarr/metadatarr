"""WHO INN / UNII drug name scraper via NCATS Inxight Drugs API.

Uses the NIH NCATS Inxight Drugs public API (no auth) which mirrors the FDA
Substance Registration System (SRS/UNII). Contains INN, USAN, BAN, JAN names
with explicit name type tagging — the same underlying data as WHO INN
recommended lists, plus all other regulatory name types.

Schema per row:
  unii, preferred_name, names[]{name, name_type, language},
  codes[]{code, code_system} (first 10), substance_class, status

Walks 10 name types, each offset-paginated against the API's own ``total``
field (not a short-page signal), so :meth:`fetch` is overridden directly.
The cursor is ``{"type_idx": i, "skip": s}``.

Blank-UNII records are all kept, matching the original (which only skipped
duplicates when the UNII was non-empty): the engine does not dedup rows whose
``id_field`` value is empty/None, since an empty id is not an identity.

Run it::

    python -m metadatarr.scrapers who_inn [--output DIR] [--delay SECS]
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PaginatedJSONSource, register, run_cli

BASE = "https://drugs.ncats.io/api/v1/substances"
PAGE = 100

# Name types to crawl — covers all regulatory naming systems
NAME_TYPES = ["INN", "USAN", "BAN", "JAN", "INN-PT", "INN-F", "INN-E", "INN-G", "INN-R", "INNM"]


@register
class WhoInnSource(PaginatedJSONSource):
    name = "who_inn"
    id_field = "unii"
    default_delay = 0.5

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

    def initial_cursor(self) -> Dict[str, int]:
        return {"type_idx": 0, "skip": 0}

    def _get_page(self, skip: int, name_type: str) -> dict:
        self.throttle.wait()
        params = {
            "top": PAGE,
            "skip": skip,
            "filter": f"names.type:{name_type}",
            "view": "full",
        }
        r = self.session().get(BASE, params=params, timeout=45)
        if r.status_code in (404, 500, 502, 503):
            return {}
        r.raise_for_status()
        return r.json()

    def map_row(self, sub: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return {
            "unii": sub.get("_approvalIDDisplay", "") or sub.get("approvalID", ""),
            "preferred_name": sub.get("_name", "") or sub.get("preferredName", ""),
            "names": [
                {
                    "name": n.get("name", ""),
                    "name_type": n.get("type", ""),
                    "language": n.get("languages", [""])[0] if n.get("languages") else "",
                }
                for n in (sub.get("names") or []) if n.get("name")
            ],
            "codes": [
                {"code": c.get("code", ""), "code_system": c.get("codeSystem", "")}
                for c in (sub.get("codes") or []) if c.get("code")
            ][:10],
            "substance_class": sub.get("substanceClass", ""),
            "status": sub.get("status", ""),
        }

    def fetch(self, cursor: Dict[str, int]):
        type_idx = int(cursor.get("type_idx", 0))
        skip = int(cursor.get("skip", 0))

        if type_idx >= len(NAME_TYPES):
            return [], None
        name_type = NAME_TYPES[type_idx]

        data = self._get_page(skip, name_type)
        items = (data.get("content") or []) if data else []

        if not data or not items:
            next_type = type_idx + 1
            next_cursor = {"type_idx": next_type, "skip": 0} if next_type < len(NAME_TYPES) else None
            return [], next_cursor

        rows = [self.map_row(sub) for sub in items]

        new_skip = skip + len(items)
        page_total = data.get("total", 0)
        if new_skip >= page_total:
            next_type = type_idx + 1
            next_cursor = {"type_idx": next_type, "skip": 0} if next_type < len(NAME_TYPES) else None
        else:
            next_cursor = {"type_idx": type_idx, "skip": new_skip}
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(WhoInnSource))
