# SPDX-License-Identifier: Apache-2.0
"""Read access to the SQLite file of one set.

A set's file holds an ``item`` table (one row per entity), an ``ext_id`` table
(external id to item), an ``alias`` table (further searchable names) and a
``meta`` table recording the dataset, its revision, the row count and the
build time. Files are opened read-only and never written here. A file that is
missing, not a database, half written or built by another schema version is
reported as absent, never raised: the caller then asks a live provider.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote

LOG = logging.getLogger("metadatarr.offline")

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE item (
    pk INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    norm TEXT NOT NULL,
    year INTEGER,
    rank REAL,
    data TEXT NOT NULL
);
CREATE TABLE ext_id (
    field TEXT NOT NULL,
    value TEXT NOT NULL,
    pk INTEGER NOT NULL,
    PRIMARY KEY (field, value, pk)
) WITHOUT ROWID;
CREATE TABLE alias (
    norm TEXT NOT NULL,
    pk INTEGER NOT NULL,
    PRIMARY KEY (norm, pk)
) WITHOUT ROWID;
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
"""
INDEXES = "CREATE INDEX item_norm ON item (norm);"

_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def normalise(text: Any) -> str:
    """Lower-case ``text`` without accents, punctuation or repeated spaces."""
    folded = unicodedata.normalize("NFKD", str(text or "")).casefold()
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return " ".join(_NON_WORD.sub(" ", folded).split())


def set_path(data_dir: Path, name: str) -> Path:
    return Path(data_dir) / f"{name}.sqlite"


@dataclass(frozen=True)
class SetInfo:
    """What the ``meta`` table records about a built set."""

    name: str
    dataset: str
    revision: str
    rows: int
    built_at: float

    def origin(self) -> Dict[str, Any]:
        return {"source": "offline", "dataset": self.dataset, "revision": self.revision,
                "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.built_at))}

    def stale(self, max_age: float, now: float) -> bool:
        return max_age > 0 and now - self.built_at > max_age


@dataclass(frozen=True)
class Row:
    """One entity as stored: ``data`` holds the item fields, ``ids`` and ``extra``."""

    set: str
    kind: str
    title: str
    year: Optional[int]
    data: Dict[str, Any]

    @property
    def ids(self) -> Dict[str, str]:
        return self.data.get("ids") or {}


_ROW = "SELECT kind, title, year, data FROM item"


class Store:
    """The SQLite files under ``data_dir``, one per set."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self._local = threading.local()
        self._warned: set = set()

    def _warn_once(self, name: str, problem: str) -> None:
        if (name, problem) not in self._warned:
            self._warned.add((name, problem))
            LOG.warning("offline set %s is unusable: %s", name, problem)

    def _open(self, name: str) -> Optional[Tuple[sqlite3.Connection, SetInfo]]:
        path = set_path(self.data_dir, name)
        try:
            stat = os.stat(path)
        except OSError:
            return None
        key = (stat.st_dev, stat.st_ino)
        cached = getattr(self._local, "open", {}).get(name)
        if cached is not None and cached[0] == key:
            return cached[1], cached[2]
        try:
            conn = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=5)
            meta = dict(conn.execute("SELECT key, value FROM meta"))
            if int(meta["schema"]) != SCHEMA_VERSION:
                raise ValueError(f"schema {meta['schema']}, expected {SCHEMA_VERSION}")
            info = SetInfo(name=name, dataset=meta["dataset"], revision=meta["revision"],
                           rows=int(meta["rows"]), built_at=float(meta["built_at"]))
            conn.execute("SELECT pk FROM item LIMIT 1").fetchall()
        except (sqlite3.Error, KeyError, ValueError) as e:
            self._warn_once(name, f"{type(e).__name__}: {e}")
            return None
        if not hasattr(self._local, "open"):
            self._local.open = {}
        old = self._local.open.get(name)
        if old is not None:
            old[1].close()
        self._local.open[name] = (key, conn, info)
        return conn, info

    def info(self, name: str) -> Optional[SetInfo]:
        opened = self._open(name)
        return opened[1] if opened else None

    def _query(self, name: str, sql: str, params: Tuple[Any, ...]) -> List[Row]:
        opened = self._open(name)
        if opened is None:
            return []
        try:
            return [Row(set=name, kind=kind, title=title, year=year, data=json.loads(data))
                    for kind, title, year, data in opened[0].execute(sql, params)]
        except (sqlite3.Error, ValueError) as e:
            self._warn_once(name, f"{type(e).__name__}: {e}")
            return []

    def find_ids(self, name: str, ids: Mapping[str, str]) -> Optional[Row]:
        """The item carrying the first of ``ids`` (field -> value) the set knows."""
        for field, value in ids.items():
            rows = self._query(
                name, f"{_ROW} WHERE pk IN (SELECT pk FROM ext_id WHERE field = ? AND value = ?) "
                      "ORDER BY rank DESC, pk LIMIT 1", (field, str(value)))
            if rows:
                return rows[0]
        return None

    def find_name(self, name: str, text: str, limit: int = 5) -> List[Row]:
        """Items whose title or alias normalises to ``text``, best ranked first."""
        norm = normalise(text)
        if not norm:
            return []
        return self._query(
            name, f"{_ROW} WHERE pk IN (SELECT pk FROM item WHERE norm = ? "
                  "UNION SELECT pk FROM alias WHERE norm = ?) ORDER BY rank DESC, pk LIMIT ?",
            (norm, norm, int(limit)))

    def close(self) -> None:
        for _, conn, _ in getattr(self._local, "open", {}).values():
            conn.close()
        self._local.open = {}
