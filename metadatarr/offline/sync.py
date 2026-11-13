# SPDX-License-Identifier: Apache-2.0
"""Fetch the parquet shards of the LeData datasets and build their SQLite files.

``metadatarr-sync --set anilist-anime`` (or ``python -m metadatarr.offline``)
reads the dataset's file list and revision from the Hub, downloads the missing
shards one at a time with a pause between files, checks each against the size
and SHA-256 the Hub reports, and builds the set's SQLite file. An interrupted
download resumes from the bytes already on disk. The Hub is only read; nothing
is ever uploaded.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, List, Optional, Sequence

import requests

from metadatarr.offline.build import BuildError, build_set
from metadatarr.offline.config import OfflineConfig
from metadatarr.offline.sets import BY_NAME, SETS, SetSpec
from metadatarr.offline.store import Store
from metadatarr.transport import USER_AGENT

HUB = "https://huggingface.co"
CHUNK = 1 << 20
ATTEMPTS = 3
#: Disk a built file is expected to need, as a multiple of the parquet bytes it is built from.
BUILD_FACTOR = 2.0


class SyncError(Exception):
    """A set could not be fetched or built."""


class InsufficientSpace(SyncError):
    """A disk lacks the room a download or build needs."""


@dataclass(frozen=True)
class HubFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class HubDataset:
    revision: str
    files: List[HubFile]


def _headers() -> dict:
    headers = {"User-Agent": USER_AGENT}
    token = os.environ.get("HF_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def hub_dataset(repo: str, session: Optional[requests.Session] = None) -> HubDataset:
    """The head revision of ``repo`` and its parquet files with the Hub's size and SHA-256."""
    http = session or requests
    info = http.get(f"{HUB}/api/datasets/{repo}", headers=_headers(), timeout=30)
    info.raise_for_status()
    revision = info.json()["sha"]
    tree = http.get(f"{HUB}/api/datasets/{repo}/tree/{revision}", params={"recursive": "true"},
                    headers=_headers(), timeout=30)
    tree.raise_for_status()
    files = [HubFile(path=e["path"], size=int(e["size"]), sha256=(e.get("lfs") or {}).get("oid", ""))
             for e in tree.json() if e.get("type") == "file" and e["path"].endswith(".parquet")]
    if not files:
        raise SyncError(f"{repo} lists no parquet file")
    return HubDataset(revision=revision, files=sorted(files, key=lambda f: f.path))


def ensure_free(path: Path, need: int, reserve: int) -> None:
    """Raise :class:`InsufficientSpace` unless ``need`` bytes fit on the disk holding
    ``path`` while ``reserve`` bytes stay free."""
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if free < need + reserve:
        raise InsufficientSpace(
            f"{probe} has {free} bytes free, {need} needed with {reserve} kept in reserve")


def _device(path: Path) -> int:
    return os.stat(path).st_dev


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_file(url: str, dest: Path, size: int, sha256: str, session: Optional[requests.Session] = None) -> None:
    """Download ``url`` to ``dest``, resuming a partial ``dest.part``, and check its
    size and (when the Hub gives one) SHA-256 before it takes its final name."""
    http = session or requests
    part = dest.with_name(dest.name + ".part")
    last: Optional[Exception] = None
    for attempt in range(ATTEMPTS):
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink()
            have = 0
        try:
            if have < size:
                headers = {**_headers(), **({"Range": f"bytes={have}-"} if have else {})}
                with http.get(url, headers=headers, stream=True, timeout=60) as response:
                    if response.status_code not in (200, 206):
                        response.raise_for_status()
                        raise SyncError(f"{url}: unexpected status {response.status_code}")
                    mode = "ab" if response.status_code == 206 else "wb"
                    with open(part, mode) as out:
                        for block in response.iter_content(CHUNK):
                            out.write(block)
            break
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
            time.sleep(2 ** attempt)
    else:
        raise SyncError(f"{url}: {type(last).__name__}: {last}")
    got = part.stat().st_size
    if got != size:
        raise SyncError(f"{dest.name}: {got} bytes on disk, the Hub reports {size}; run again to resume")
    if sha256 and _sha256(part) != sha256:
        part.unlink()
        raise SyncError(f"{dest.name}: SHA-256 differs from the Hub's; the partial file was removed")
    os.replace(part, dest)


def sync_set(spec: SetSpec, config: OfflineConfig, *, force: bool = False,
             session: Optional[requests.Session] = None,
             sleep: Callable[[float], None] = time.sleep,
             log: Callable[[str], None] = print) -> Optional[int]:
    """Bring ``spec``'s SQLite file up to the Hub's head revision; the row count
    built, or ``None`` when the file already is at that revision."""
    if not config.enabled:
        raise SyncError("set METADATARR_OFFLINE_DIR (or --data-dir) first")
    hub = hub_dataset(spec.repo, session)
    built = Store(config.data_dir).info(spec.name)
    if built is not None and built.revision == hub.revision and not force:
        log(f"{spec.name}: up to date at {hub.revision[:12]}")
        return None
    shard_dir = config.fetch_dir / spec.name / hub.revision
    wanted = [(f, shard_dir / Path(f.path).name) for f in hub.files]
    todo = [(f, dest) for f, dest in wanted if not (dest.exists() and dest.stat().st_size == f.size)]
    total = sum(f.size for f in hub.files)
    fetch_bytes = sum(f.size - (dest.with_name(dest.name + ".part").stat().st_size
                                if dest.with_name(dest.name + ".part").exists() else 0) for f, dest in todo)
    shard_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if _device(shard_dir) == _device(config.data_dir):
        ensure_free(shard_dir, fetch_bytes + int(total * BUILD_FACTOR), config.min_free)
    else:
        ensure_free(shard_dir, fetch_bytes, config.min_free)
        ensure_free(config.data_dir, int(total * BUILD_FACTOR), config.min_free)
    for n, (f, dest) in enumerate(todo):
        if n:
            sleep(config.gap)
        log(f"{spec.name}: fetching {f.path} ({f.size} bytes)")
        fetch_file(f"{HUB}/datasets/{spec.repo}/resolve/{hub.revision}/{f.path}", dest, f.size, f.sha256, session)
    log(f"{spec.name}: building from {len(wanted)} shard(s)")
    info = build_set(spec, [dest for _, dest in wanted], config.data_dir, dataset=spec.repo,
                     revision=hub.revision, clock=time.time)
    log(f"{spec.name}: {info.rows} rows at {info.revision[:12]}")
    return info.rows


def _status(config: OfflineConfig, log: Callable[[str], None]) -> None:
    store = Store(config.data_dir)
    for spec in SETS:
        info = store.info(spec.name)
        if info is None:
            log(f"{spec.name}: not built")
        else:
            built = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(info.built_at))
            log(f"{spec.name}: {info.rows} rows, revision {info.revision[:12]}, built {built} UTC")


def main(argv: Optional[Sequence[str]] = None, *, session: Optional[requests.Session] = None,
         sleep: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(
        prog="metadatarr-sync",
        description="Fetch LeData parquet datasets from the Hugging Face Hub and build the SQLite files "
                    "the offline layer reads. The Hub is only read.")
    parser.add_argument("--set", dest="sets", action="append", default=[], metavar="NAME",
                        help="a set to sync; repeat for several (see --list)")
    parser.add_argument("--all", action="store_true", help="sync every set")
    parser.add_argument("--list", action="store_true", help="list the sets and exit")
    parser.add_argument("--status", action="store_true", help="show what is built and exit")
    parser.add_argument("--force", action="store_true", help="rebuild even when the revision is unchanged")
    parser.add_argument("--data-dir", help="SQLite directory (default: METADATARR_OFFLINE_DIR)")
    parser.add_argument("--cache-dir", help="parquet download directory (default: METADATARR_OFFLINE_CACHE_DIR)")
    parser.add_argument("--gap", type=float, help="seconds between downloads (default: METADATARR_OFFLINE_GAP)")
    args = parser.parse_args(argv)

    if args.list:
        for spec in SETS:
            print(f"{spec.name}\t{spec.repo}")
        return 0
    config = OfflineConfig.from_env()
    overrides = {}
    if args.data_dir:
        overrides["data_dir"] = Path(args.data_dir).expanduser()
    if args.cache_dir:
        overrides["cache_dir"] = Path(args.cache_dir).expanduser()
    if args.gap is not None:
        overrides["gap"] = args.gap
    if overrides:
        config = replace(config, **overrides)
    if not config.enabled:
        print("metadatarr-sync: set METADATARR_OFFLINE_DIR or pass --data-dir", file=sys.stderr)
        return 2
    if args.status:
        _status(config, print)
        return 0
    unknown = [n for n in args.sets if n not in BY_NAME]
    if unknown:
        print(f"metadatarr-sync: unknown set {', '.join(unknown)}; see --list", file=sys.stderr)
        return 2
    chosen = list(SETS) if args.all else [BY_NAME[n] for n in dict.fromkeys(args.sets)]
    if not chosen:
        print("metadatarr-sync: name a set with --set or use --all", file=sys.stderr)
        return 2
    failed = 0
    fetched = False
    for spec in chosen:
        if fetched:
            sleep(config.gap)
        try:
            fetched = sync_set(spec, config, force=args.force, session=session, sleep=sleep) is not None
        except (SyncError, BuildError, requests.RequestException) as e:
            print(f"{spec.name}: {e}", file=sys.stderr)
            failed += 1
            fetched = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
