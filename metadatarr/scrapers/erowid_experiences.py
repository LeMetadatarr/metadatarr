"""Erowid experience-report and substance-vault crawlers.

Thin wrappers around ``pyerowid`` (block-detection, adaptive backoff, and
Wayback Machine fallback all live there — see
``/home/miro/AgentWorkspaces/clients/psychonautics/pyerowid``) that route
output through the engine instead of pyerowid's own ``export_jsonl``/checkpoint
helpers. Two independent :class:`~metadatarr.scrapers.engine.Source`
registrations, one per original dataset:

* :class:`ErowidExperiencesSource` (``erowid_experiences``) — first-person
  reports, exp_id 1..``MAX_EXPERIENCE_ID`` (~111k). Walked in fixed-size id
  chunks (matching the original's checkpoint interval) rather than one id at
  a time, so :meth:`fetch` is overridden directly; the cursor is the next
  exp_id to try. Already-collected ids (``self._seen``, from ``id_field``)
  are skipped *before* hitting the network, mirroring the original's ``done``
  set passed into ``pyerowid.dataset.iter_experiences``.
* :class:`ErowidSubstancesSource` (``erowid_substances``) — vault pages
  (pharms/chemicals/plants/herbs/smarts/animals). Walked one category per
  page; the cursor is the category index into ``sorted(_CATEGORY_BASES)``
  (stable, matching the original's iteration order).

Row shape is reused verbatim from ``pyerowid.dataset._exp_row`` /
``_substance_row`` (via :meth:`map_row`) so the JSONL contract can't drift
from pyerowid's own.

Erowid is a small harm-reduction non-profit — be polite: default delay is 2s.

Run them::

    python -m metadatarr.scrapers erowid_experiences [--output DIR] [--delay SECS]
    python -m metadatarr.scrapers erowid_substances [--output DIR] [--delay SECS]
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from metadatarr.scrapers.engine import Source, register, run_cli

LOG = logging.getLogger("metadatarr.scrapers")

try:
    from pyerowid._transport import Transport
    from pyerowid.dataset import _exp_row, _substance_row
    from pyerowid.reports import (
        _CATEGORY_BASES,
        MAX_EXPERIENCE_ID,
        _extract_list,
        get_experience,
        parse_substance_page,
    )
except ImportError as exc:  # pragma: no cover - exercised only without the dep
    raise ImportError(
        "erowid_experiences.py requires pyerowid.\n"
        "Install with: uv pip install -e "
        "/home/miro/AgentWorkspaces/clients/psychonautics/pyerowid"
    ) from exc

EXP_CHUNK = 500


@register
class ErowidExperiencesSource(Source):
    name = "erowid_experiences"
    id_field = "exp_id"
    default_delay = 2.0

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self._transport: Optional[Transport] = None

    def _get_transport(self) -> Transport:
        if self._transport is None:
            self._transport = Transport(delay=self.throttle.min_delay)
        return self._transport

    def map_row(self, exp: Any) -> Dict[str, Any]:
        return _exp_row(exp)

    def initial_cursor(self) -> int:
        return 1

    def fetch(self, cursor: int):
        start = int(cursor or 1)
        if start > MAX_EXPERIENCE_ID:
            return [], None
        end = min(start + EXP_CHUNK - 1, MAX_EXPERIENCE_ID)
        seen = getattr(self, "_seen", set())
        transport = self._get_transport()

        rows = []
        for exp_id in range(start, end + 1):
            if str(exp_id) in seen:
                continue
            self.throttle.wait()
            exp = get_experience(exp_id, transport=transport)
            if exp is None:
                continue
            rows.append(self.map_row(exp))

        next_cursor = end + 1 if end < MAX_EXPERIENCE_ID else None
        return rows, next_cursor


@register
class ErowidSubstancesSource(Source):
    name = "erowid_substances"
    id_field = "name"
    default_delay = 2.0

    def __init__(self, *, delay: Optional[float] = None) -> None:
        super().__init__(delay=delay)
        self._transport: Optional[Transport] = None

    def _get_transport(self) -> Transport:
        if self._transport is None:
            self._transport = Transport(delay=self.throttle.min_delay)
        return self._transport

    def map_row(self, info: Any) -> Dict[str, Any]:
        return _substance_row(info)

    def initial_cursor(self) -> int:
        return 0

    def fetch(self, cursor: int):
        categories = sorted(_CATEGORY_BASES)
        idx = int(cursor or 0)
        if idx >= len(categories):
            return [], None
        category = categories[idx]
        transport = self._get_transport()

        try:
            listings = _extract_list(category, transport=transport)
        except Exception as exc:
            LOG.warning("[%s] category %r index failed: %s", self.name, category, exc)
            listings = []

        seen = getattr(self, "_seen", set())
        rows = []
        for listing in listings:
            if listing.name in seen:
                continue
            try:
                info = parse_substance_page(listing.url, transport=transport)
            except Exception as exc:
                LOG.warning("[%s] %s: %s", self.name, listing.name, exc)
                continue
            self.throttle.wait()
            rows.append(self.map_row(info))

        next_idx = idx + 1
        next_cursor = next_idx if next_idx < len(categories) else None
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(ErowidExperiencesSource))
