# SPDX-License-Identifier: Apache-2.0
"""Build the SQLite file of one set from its parquet shards.

The file is written under a temporary name inside the data directory and
renamed over the live file only when it is complete and consistent, so a
failed or interrupted build leaves the previous file untouched.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from metadatarr.offline.sets import SetSpec
from metadatarr.offline.store import INDEXES, SCHEMA, SCHEMA_VERSION, SetInfo, normalise, set_path

BATCH_ROWS = 4096
#: Longest text kept for one column, and most entries kept of one list.
MAX_TEXT = 2000
MAX_LIST = 25
MAX_NAMES = 20
MAX_IDS = 20

_YEAR = re.compile(r"(?<![0-9])([0-9]{4})(?![0-9])")


class BuildError(Exception):
    """The shards cannot be turned into a set (missing column, row count mismatch)."""


def year_of(value: Any) -> Optional[int]:
    """The first plausible four-digit year in an integer, date or free text."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if 1000 <= value <= 2200 else None
    for found in _YEAR.findall(str(value)):
        if 1000 <= int(found) <= 2200:
            return int(found)
    return None


def _text(value: Any) -> str:
    if value is None or isinstance(value, (list, dict)):
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return str(value).strip()


def _first(rec: Dict[str, Any], columns: str) -> str:
    for column in columns.split("|"):
        found = _text(rec.get(column))
        if found:
            return found
    return ""


def _plain(value: Any) -> Any:
    """``value`` reduced to what JSON holds, long text and lists cut."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value[:MAX_LIST]]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if value is None or isinstance(value, (bool, int)):
        return value
    return str(value)[:MAX_TEXT]


def _values(value: Any) -> List[str]:
    items = value if isinstance(value, (list, tuple)) else [value]
    return [t for t in (_text(v) for v in items) if t]


def _person(value: Any) -> str:
    """A creator's name from text, a name record or a JSON-encoded name record."""
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            value = json.loads(value)
        except ValueError:
            return value.strip()
    if isinstance(value, dict):
        name = _text(value.get("name"))
        return name or " ".join(t for t in (_text(value.get("first_name")), _text(value.get("last_name"))) if t)
    return _text(value)


def _clean_id(field: str, value: str) -> str:
    return value.replace("-", "").upper() if field in ("isbn_10", "isbn_13") else value


def convert(spec: SetSpec, rec: Dict[str, Any]) -> Optional[Tuple[str, Optional[int], Optional[float],
                                                                     Dict[str, Any], List[Tuple[str, str]],
                                                                     List[str]]]:
    """``(title, year, rank, data, ext_ids, names)`` for one row, ``None`` without a title."""
    title = _first(rec, "|".join(spec.title))
    if not title:
        return None
    kind = spec.kind
    if spec.kind_by:
        kind = spec.kind_by[1].get(_text(rec.get(spec.kind_by[0])), kind)
    data: Dict[str, Any] = {"kind": kind, "title": title}
    for name, column in spec.fields.items():
        value = _first(rec, column)
        if name == "runtime_min":
            try:
                minutes = round(float(value) * spec.runtime_unit, 2) if value else 0
            except ValueError:
                minutes = 0
            if minutes > 0:
                data[name] = minutes
        elif value:
            data[name] = value[:MAX_TEXT]
    if spec.poster:
        value = _text(rec.get(spec.poster[0]))
        if value:
            data["poster_url"] = spec.poster[1].format(value)
    if spec.artist:
        raw = rec.get(spec.artist)
        creator = _person(raw[0] if isinstance(raw, (list, tuple)) and raw else raw)
        if creator:
            data["artist"] = creator
    ext_ids: List[Tuple[str, str]] = []
    ids: Dict[str, str] = {}
    for column, field in spec.ids.items():
        for value in _values(rec.get(column))[:MAX_IDS]:
            value = _clean_id(field, value)
            ids.setdefault(field, value)
            ext_ids.append((field, value))
    if ids:
        data["ids"] = ids
    extra = {c: _plain(rec[c]) for c in spec.keep
             if rec.get(c) not in (None, "", [], {}) and not (isinstance(rec[c], float) and math.isnan(rec[c]))}
    if extra:
        data["extra"] = extra
    year = year_of(rec.get(spec.year)) if spec.year else None
    if year is None:
        year = year_of(data.get("release_date"))
    rank = None
    if spec.rank:
        try:
            rank = float(rec.get(spec.rank))
        except (TypeError, ValueError):
            rank = None
        if rank is not None and not math.isfinite(rank):
            rank = None
    norm = normalise(title)
    names: List[str] = []
    for column in spec.names:
        for value in _values(rec.get(column)):
            n = normalise(value)
            if n and n != norm and n not in names:
                names.append(n)
    for column in spec.title[1:]:
        n = normalise(rec.get(column))
        if n and n != norm and n not in names:
            names.append(n)
    return title, year, rank, data, ext_ids, names[:MAX_NAMES]


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _discard(tmp: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.unlink(f"{tmp}{suffix}")
        except FileNotFoundError:
            pass


def _parquet():
    try:
        import pyarrow.parquet as pq
    except ImportError as e:
        raise BuildError("building a set needs pyarrow; install metadatarr[offline]") from e
    return pq


def build_set(spec: SetSpec, shards: Sequence[Path], data_dir: Path, *, dataset: str, revision: str,
              clock: Callable[[], float] = time.time,
              progress: Optional[Callable[[int], None]] = None) -> SetInfo:
    """Write ``<data_dir>/<name>.sqlite`` from ``shards`` and return what it records.

    Raises :class:`BuildError` when a shard lacks a required column or the rows
    read do not add up to the rows the shards declare; the previous file, if
    any, is then left as it was."""
    pq = _parquet()
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    final = set_path(data_dir, spec.name)
    tmp = final.with_name(final.name + ".building")
    _discard(tmp)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript("PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;" + SCHEMA)
        expected = inserted = skipped = 0
        for shard in shards:
            reader = pq.ParquetFile(str(shard))
            present = set(reader.schema_arrow.names)
            missing = [c for c in spec.required if c not in present]
            if missing:
                raise BuildError(f"{shard.name} of {dataset} has no column {', '.join(missing)}")
            expected += reader.metadata.num_rows
            for batch in reader.iter_batches(batch_size=BATCH_ROWS,
                                             columns=[c for c in spec.columns if c in present]):
                items, ext_ids, aliases = [], [], []
                for rec in batch.to_pylist():
                    done = convert(spec, rec)
                    if done is None:
                        skipped += 1
                        continue
                    title, year, rank, data, row_ids, names = done
                    inserted += 1
                    items.append((inserted, data["kind"], title, normalise(title), year, rank,
                                  json.dumps(data, ensure_ascii=False, separators=(",", ":"))))
                    ext_ids.extend((f, v, inserted) for f, v in row_ids)
                    aliases.extend((n, inserted) for n in names)
                conn.executemany("INSERT INTO item VALUES (?,?,?,?,?,?,?)", items)
                conn.executemany("INSERT OR IGNORE INTO ext_id VALUES (?,?,?)", ext_ids)
                conn.executemany("INSERT OR IGNORE INTO alias VALUES (?,?)", aliases)
                if progress:
                    progress(inserted)
        if inserted + skipped != expected:
            raise BuildError(f"{dataset}: read {inserted + skipped} rows, shards declare {expected}")
        if inserted == 0:
            raise BuildError(f"{dataset}: no row has a title")
        conn.executescript(INDEXES)
        built_at = clock()
        conn.executemany("INSERT INTO meta VALUES (?,?)", [
            ("schema", str(SCHEMA_VERSION)), ("set", spec.name), ("dataset", dataset),
            ("revision", revision), ("rows", str(inserted)), ("skipped", str(skipped)),
            ("built_at", repr(built_at)), ("files", json.dumps([Path(s).name for s in shards]))])
        conn.commit()
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        fd = os.open(tmp, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, final)
        _sync_dir(data_dir)
    except BaseException:
        conn.close()
        _discard(tmp)
        raise
    return SetInfo(name=spec.name, dataset=dataset, revision=revision, rows=inserted, built_at=built_at)
