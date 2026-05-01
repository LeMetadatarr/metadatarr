"""Persistence + reverse-index helpers for :class:`EntitySidecar`.

The base :class:`~metadatarr.resolve.entities.EntitySidecar` is just a
Pydantic model with a ``{entity_id: EntityRecord}`` dict. This module adds:

- JSON load/save (no extra dependency — Pydantic round-trips via
  ``model_dump_json`` / ``model_validate_json``);
- a reverse index keyed by alias and by external id, so callers can ask
  "do we already have an entity for this MBID?" in O(1) without scanning
  the entire entities dict.

The index is opt-in. Builders can call :func:`build_index` once after
loading the sidecar and re-use the returned :class:`SidecarIndex` for as
long as the sidecar contents are stable.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from metadatarr.resolve.entities import (
    EntityKind,
    EntityRecord,
    EntitySidecar,
)
from metadatarr.resolve.external_ids import ExternalIds


# ---------------------------------------------------------------------------
# JSON load / save
# ---------------------------------------------------------------------------

def save(sidecar: EntitySidecar, path: os.PathLike) -> None:
    """Atomically write *sidecar* to *path* as UTF-8 JSON.

    Writes to a sibling tempfile and ``os.replace`` to avoid leaving a
    half-written file behind if the process is interrupted.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = sidecar.model_dump_json(indent=2, exclude_none=True)
    fd, tmpname = tempfile.mkstemp(prefix=p.name + ".", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmpname, p)
    except Exception:
        # Clean up tempfile on any failure.
        try:
            os.unlink(tmpname)
        except FileNotFoundError:
            pass
        raise


def load(path: os.PathLike) -> EntitySidecar:
    """Load an :class:`EntitySidecar` from JSON. Empty/missing path → empty sidecar."""
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return EntitySidecar()
    with open(p, "r", encoding="utf-8") as fh:
        data = fh.read()
    return EntitySidecar.model_validate_json(data)


# ---------------------------------------------------------------------------
# Reverse index
# ---------------------------------------------------------------------------

# Tuple of (kind, key, value) — e.g. ("artist", "musicbrainz_artist", "abc-123").
_IndexKey = Tuple[str, str, str]


@dataclass
class SidecarIndex:
    """O(1) reverse lookup over an :class:`EntitySidecar`.

    Built once via :func:`build_index`; rebuild after batch updates.
    """

    by_external_id: Dict[_IndexKey, str] = field(default_factory=dict)
    """``(kind, ext-field, value) -> entity_id``"""
    by_alias: Dict[Tuple[str, str], Set[str]] = field(default_factory=dict)
    """``(kind, normalised-name) -> {entity_id, ...}``"""

    def find_by_external_id(self, kind: EntityKind, field_name: str,
                            value: str) -> Optional[str]:
        return self.by_external_id.get((kind.value, field_name, str(value)))

    def find_by_name(self, kind: EntityKind, name: str) -> List[str]:
        from metadatarr.resolve.entities import _normalize_name
        ids = self.by_alias.get((kind.value, _normalize_name(name)), set())
        return list(ids)


def build_index(sidecar: EntitySidecar) -> SidecarIndex:
    """Walk *sidecar* and emit a reverse index over alias names + external ids."""
    from metadatarr.resolve.entities import _normalize_name

    idx = SidecarIndex()
    for entity_id, rec in sidecar.entities.items():
        # External-id index
        for fname in ExternalIds.model_fields:
            if fname == "extra":
                continue
            val = getattr(rec.external_ids, fname, None)
            if val in (None, ""):
                continue
            idx.by_external_id[(rec.kind.value, fname, str(val))] = entity_id
        for k, v in rec.external_ids.extra.items():
            if v:
                idx.by_external_id[(rec.kind.value, k, str(v))] = entity_id

        # Alias / name index
        for surface in [rec.name, *rec.aliases]:
            if not surface:
                continue
            key = (rec.kind.value, _normalize_name(surface))
            idx.by_alias.setdefault(key, set()).add(entity_id)
    return idx


__all__ = [
    "SidecarIndex",
    "build_index",
    "load",
    "save",
]
