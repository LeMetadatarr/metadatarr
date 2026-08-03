"""Shared resumable-state helpers for metadatarr bulk scrapers.

Every scraper:
  - appends rows to  {output_dir}/{name}.jsonl  (one JSON object per line)
  - saves cursor to  {output_dir}/{name}_checkpoint.json  (atomic write)

On restart the scraper calls load_checkpoint() to get its cursor, then
load_existing_ids() to rebuild the dedup-set from already-written rows.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

_DEFAULT_OUTPUT = Path.home() / ".cache" / "metadatarr" / "scrapers"


def default_output_dir() -> Path:
    return _DEFAULT_OUTPUT


def _jsonl_path(name: str, output_dir: Path) -> Path:
    return output_dir / f"{name}.jsonl"


def _ckpt_path(name: str, output_dir: Path) -> Path:
    return output_dir / f"{name}_checkpoint.json"


# ---------------------------------------------------------------------------
# Checkpoint load / save
# ---------------------------------------------------------------------------

def load_checkpoint(name: str, output_dir: Path) -> Dict[str, Any]:
    """Return saved checkpoint dict, or {} if none exists."""
    path = _ckpt_path(name, output_dir)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_checkpoint(name: str, state: Dict[str, Any], output_dir: Path) -> None:
    """Atomically write checkpoint state to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = _ckpt_path(name, output_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# JSONL append
# ---------------------------------------------------------------------------

def append_rows(name: str, rows: Iterable[Dict[str, Any]], output_dir: Path) -> int:
    """Append rows to the JSONL file. Returns number of rows written."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = _jsonl_path(name, output_dir)
    count = 0
    with open(path, "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def load_existing_ids(name: str, id_field: str, output_dir: Path) -> Set[str]:
    """Read existing JSONL and return the set of already-fetched IDs."""
    path = _jsonl_path(name, output_dir)
    seen: Set[str] = set()
    if not path.exists():
        return seen
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                val = obj.get(id_field)
                if val is not None:
                    seen.add(str(val))
            except Exception:
                continue
    return seen


def count_rows(name: str, output_dir: Path) -> int:
    path = _jsonl_path(name, output_dir)
    if not path.exists():
        return 0
    count = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                count += 1
    return count


# ---------------------------------------------------------------------------
# Rate-limit helper
# ---------------------------------------------------------------------------

class Throttle:
    """Simple per-scraper rate limiter."""

    def __init__(self, min_delay: float = 1.0):
        self.min_delay = min_delay
        self._last: float = 0.0

    def wait(self) -> None:
        elapsed = time.time() - self._last
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self._last = time.time()
