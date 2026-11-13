# SPDX-License-Identifier: Apache-2.0
"""Settings of the offline layer, read from ``METADATARR_OFFLINE_*``.

The layer is off unless ``METADATARR_OFFLINE_DIR`` names the directory that
holds the SQLite files. The Hub cache for the downloaded parquet shards is a
separate setting so that it can live on a larger disk; ``HF_HOME`` is never
read, because it also holds credentials.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

DEFAULT_MAX_AGE = 30 * 24 * 3600
DEFAULT_GAP = 20.0
DEFAULT_MIN_FREE = 1 << 30
#: Directory name inside ``HF_HUB_CACHE`` for the shards this package fetches.
CACHE_SUBDIR = "metadatarr-ledata"


@dataclass(frozen=True)
class OfflineConfig:
    """``data_dir``: where the SQLite files live; ``None`` disables the layer.
    ``cache_dir``: where parquet shards are downloaded and resumed.
    ``max_age``: seconds after which an offline row counts as stale and a live
    provider is asked instead; ``0`` never expires.
    ``gap``: seconds to wait between two downloads.
    ``min_free``: bytes that must stay free on a disk after a download or build."""

    data_dir: Optional[Path] = None
    cache_dir: Optional[Path] = None
    max_age: float = DEFAULT_MAX_AGE
    gap: float = DEFAULT_GAP
    min_free: int = DEFAULT_MIN_FREE

    @property
    def enabled(self) -> bool:
        return self.data_dir is not None

    @property
    def fetch_dir(self) -> Optional[Path]:
        if self.cache_dir is not None:
            return self.cache_dir
        return self.data_dir / ".parquet" if self.data_dir is not None else None

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "OfflineConfig":
        env = os.environ if env is None else env

        def path(name: str) -> Optional[Path]:
            raw = env.get(name, "").strip()
            return Path(raw).expanduser() if raw else None

        cache = path("METADATARR_OFFLINE_CACHE_DIR")
        if cache is None and path("HF_HUB_CACHE") is not None:
            cache = path("HF_HUB_CACHE") / CACHE_SUBDIR
        return cls(
            data_dir=path("METADATARR_OFFLINE_DIR"),
            cache_dir=cache,
            max_age=float(env.get("METADATARR_OFFLINE_MAX_AGE", "") or DEFAULT_MAX_AGE),
            gap=float(env.get("METADATARR_OFFLINE_GAP", "") or DEFAULT_GAP),
            min_free=int(env.get("METADATARR_OFFLINE_MIN_FREE", "") or DEFAULT_MIN_FREE),
        )
