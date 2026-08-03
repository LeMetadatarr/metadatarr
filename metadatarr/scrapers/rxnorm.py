"""RxNorm drug name normalization crawler.

Fetches all drug concepts from the NIH RxNorm REST API (no auth required)
across ten term types (``_TARGET_TTYS``), enriching ingredient-class concepts
(``tty == "IN"``) with ATC crossref codes. The concept list itself isn't
paginated by the API (one ``allconcepts`` call per TTY returns everything),
so the walk is over that in-memory list rather than an offset — :meth:`fetch`
paginates through it in fixed-size batches, fetching the concept list lazily
on first call and caching it on the instance. The cursor is the index into
that cached list.

Deviation: the original checked ``concept.rxcui not in seen`` once up front
to skip already-collected concepts entirely (saving the ATC lookup, not just
the write); this port does the same check per-batch against ``self._seen``
(the engine's persisted id set) before making the ATC call, so restarts don't
redo ATC lookups for already-harvested ingredients either.

The dataset/checkpoint name is kept as ``rxnorm_drugs`` (the original's
``NAME``), even though this module is ``rxnorm.py``, so the output JSONL
filename doesn't change.

Schema per row:
  rxcui, name, tty (term type), atc_codes []

Run it::

    python -m metadatarr.scrapers rxnorm [--output DIR] [--delay SECS]
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import Source, _HttpMixin, register, run_cli

BASE = "https://rxnav.nlm.nih.gov/REST"
TARGET_TTYS = ["IN", "BN", "SCD", "SBD", "SCDC", "SBDC", "GPCK", "BPCK", "MIN", "PIN"]
BATCH = 50


@register
class RxNormSource(_HttpMixin, Source):
    name = "rxnorm_drugs"
    id_field = "rxcui"
    default_delay = 0.15

    accept = "application/json"

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self._concepts: Optional[List[dict]] = None

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

    def _get(self, path: str, **params) -> dict:
        self.throttle.wait()
        url = f"{BASE}/{path.lstrip('/')}"
        if not url.endswith(".json"):
            url += ".json"
        r = self.session().get(url, params=params or None, timeout=30)
        r.raise_for_status()
        return r.json()

    def _all_concepts(self) -> List[dict]:
        """Fetch (and cache) all concepts for all target TTYs, deduped by rxcui."""
        if self._concepts is not None:
            return self._concepts
        all_concepts: List[dict] = []
        for tty in TARGET_TTYS:
            try:
                data = self._get("allconcepts", tty=tty)
                concepts = (data.get("minConceptGroup") or {}).get("minConcept") or []
                all_concepts.extend(concepts)
            except Exception:
                pass
        seen_for_dedup: dict = {}
        for c in all_concepts:
            cid = c.get("rxcui", "")
            if cid and cid not in seen_for_dedup:
                seen_for_dedup[cid] = c
        self._concepts = list(seen_for_dedup.values())
        return self._concepts

    def _get_atc(self, rxcui: str) -> List[str]:
        """Fetch ATC codes for an ingredient CUI via the property endpoint."""
        try:
            data = self._get(f"rxcui/{rxcui}/property", propName="ATC")
            props = (data.get("propConceptGroup") or {}).get("propConcept") or []
            return [p["propValue"] for p in props if p.get("propValue")]
        except Exception:
            return []

    def map_row(self, concept: Dict[str, Any], atc: List[str]) -> Dict[str, Any]:
        return {
            "rxcui": concept.get("rxcui", ""),
            "name": concept.get("name", ""),
            "tty": concept.get("tty", ""),
            "atc_codes": atc,
        }

    def initial_cursor(self) -> int:
        return 0

    def fetch(self, cursor: int):
        concepts = self._all_concepts()
        idx = int(cursor or 0)
        if idx >= len(concepts):
            return [], None

        seen = getattr(self, "_seen", set())
        batch = concepts[idx: idx + BATCH]
        rows = []
        for concept in batch:
            rxcui = concept.get("rxcui", "")
            if rxcui and rxcui in seen:
                continue
            tty = concept.get("tty", "")
            atc = self._get_atc(rxcui) if tty == "IN" else []
            rows.append(self.map_row(concept, atc))

        next_idx = idx + BATCH
        next_cursor = next_idx if next_idx < len(concepts) else None
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(RxNormSource))
