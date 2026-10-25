# SPDX-License-Identifier: Apache-2.0
"""Fetching parquet shards from a stand-in Hub and building the SQLite file. No
request leaves the process: the session is a fake that serves the Hub's API
and file downloads from memory."""
from __future__ import annotations

import hashlib
from collections import namedtuple
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from metadatarr.offline import sync  # noqa: E402
from metadatarr.offline.config import OfflineConfig  # noqa: E402
from metadatarr.offline.sets import BY_NAME  # noqa: E402
from metadatarr.offline.store import Store  # noqa: E402
from tests._offline_fixtures import SAMPLES, write_shard  # noqa: E402

SPEC = BY_NAME["tvmaze-shows"]
REPO = SPEC.repo
Usage = namedtuple("Usage", "total used free")


class Reply:
    def __init__(self, status=200, body=None, payload=None):
        self.status_code, self._body, self._payload = status, body, payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def iter_content(self, size):
        for i in range(0, len(self._body), size):
            yield self._body[i:i + size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHub:
    """Serves one dataset: the API answers, and the shards honouring ``Range``."""

    def __init__(self, tmp_path, shard_rows, revision="rev1"):
        self.revision = revision
        self.files = {}
        for n, rows in enumerate(shard_rows):
            path = write_shard(tmp_path / "hub" / f"{n}.parquet", rows)
            self.files[f"data/train-0000{n}-of-0000{len(shard_rows)}.parquet"] = path.read_bytes()
        self.calls = []
        self.advertised_size = {}
        self.advertised_sha = {}
        self.truncate_to = None

    def tree(self):
        return [{"type": "file", "path": ".gitattributes", "size": 3},
                *({"type": "file", "path": p,
                   "size": self.advertised_size.get(p, len(b)),
                   "lfs": {"oid": self.advertised_sha.get(p, hashlib.sha256(b).hexdigest())}}
                  for p, b in self.files.items())]

    def get(self, url, headers=None, stream=False, timeout=None, params=None):
        self.calls.append((url, dict(headers or {})))
        if url.endswith(f"/api/datasets/{REPO}"):
            return Reply(payload={"sha": self.revision})
        if url.endswith(f"/api/datasets/{REPO}/tree/{self.revision}"):
            assert params == {"recursive": "true"}
            return Reply(payload=self.tree())
        prefix = f"{sync.HUB}/datasets/{REPO}/resolve/{self.revision}/"
        assert url.startswith(prefix), url
        body = self.files[url[len(prefix):]]
        if self.truncate_to is not None:
            body = body[:self.truncate_to]
        rng = (headers or {}).get("Range")
        if rng:
            start = int(rng.split("=")[1].rstrip("-"))
            return Reply(206, body[start:])
        return Reply(200, body)

    def downloads(self):
        return [c for c in self.calls if "/resolve/" in c[0]]


def config(tmp_path, **kw):
    return OfflineConfig(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", gap=7.0, min_free=0, **kw)


def rows(*ids):
    return [{**SAMPLES["tvmaze-shows"]["row"], "tvmaze_id": str(i), "name": f"Show {i}", "imdb_id": f"tt{i:07d}"}
            for i in ids]


def test_sync_downloads_each_shard_with_a_gap_and_builds_the_set(tmp_path):
    hub, pauses, lines = FakeHub(tmp_path, [rows(1, 2), rows(3)]), [], []
    built = sync.sync_set(SPEC, config(tmp_path), session=hub, sleep=pauses.append, log=lines.append)
    assert built == 3
    assert pauses == [7.0]
    info = Store(tmp_path / "data").info("tvmaze-shows")
    assert (info.revision, info.rows, info.dataset) == ("rev1", 3, REPO)
    assert Store(tmp_path / "data").find_ids("tvmaze-shows", {"imdb": "tt0000003"}).title == "Show 3"
    cached = sorted(p.name for p in (tmp_path / "cache" / "tvmaze-shows" / "rev1").iterdir())
    assert cached == ["train-00000-of-00002.parquet", "train-00001-of-00002.parquet"]
    assert len(hub.downloads()) == 2


def test_nothing_is_written_outside_the_data_and_cache_directories(tmp_path):
    hub = FakeHub(tmp_path, [rows(1)])
    sync.sync_set(SPEC, config(tmp_path), session=hub, sleep=lambda s: None, log=lambda m: None)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cache", "data", "hub"]


def test_an_unchanged_revision_downloads_nothing(tmp_path):
    hub = FakeHub(tmp_path, [rows(1)])
    cfg = config(tmp_path)
    sync.sync_set(SPEC, cfg, session=hub, sleep=lambda s: None, log=lambda m: None)
    hub.calls.clear()
    assert sync.sync_set(SPEC, cfg, session=hub, sleep=lambda s: None, log=lambda m: None) is None
    assert hub.downloads() == []
    assert sync.sync_set(SPEC, cfg, force=True, session=hub, sleep=lambda s: None, log=lambda m: None) == 1


def test_a_new_revision_is_fetched_and_replaces_the_set(tmp_path):
    hub = FakeHub(tmp_path, [rows(1)])
    cfg = config(tmp_path)
    sync.sync_set(SPEC, cfg, session=hub, sleep=lambda s: None, log=lambda m: None)
    hub.revision = "rev2"
    hub.files = {p: b for p, b in FakeHub(tmp_path / "second", [rows(8, 9)]).files.items()}
    assert sync.sync_set(SPEC, cfg, session=hub, sleep=lambda s: None, log=lambda m: None) == 2
    assert Store(tmp_path / "data").info("tvmaze-shows").revision == "rev2"


def test_an_interrupted_download_resumes_from_the_bytes_on_disk(tmp_path):
    hub = FakeHub(tmp_path, [rows(1, 2, 3)])
    name, body = next(iter(hub.files.items()))
    part = tmp_path / "cache" / "tvmaze-shows" / "rev1" / (Path(name).name + ".part")
    part.parent.mkdir(parents=True)
    part.write_bytes(body[:100])
    sync.sync_set(SPEC, config(tmp_path), session=hub, sleep=lambda s: None, log=lambda m: None)
    (url, headers), = hub.downloads()
    assert headers["Range"] == "bytes=100-"
    assert (part.parent / Path(name).name).read_bytes() == body
    assert not part.exists()
    assert Store(tmp_path / "data").info("tvmaze-shows").rows == 3


def test_a_server_that_ignores_range_restarts_the_file(tmp_path):
    hub = FakeHub(tmp_path, [rows(1)])
    name, body = next(iter(hub.files.items()))
    part = tmp_path / "cache" / "tvmaze-shows" / "rev1" / (Path(name).name + ".part")
    part.parent.mkdir(parents=True)
    part.write_bytes(b"stale bytes that are not a prefix")
    real_get = hub.get
    hub.get = lambda url, headers=None, **kw: real_get(url, {k: v for k, v in (headers or {}).items()
                                                            if k != "Range"}, **kw)
    sync.sync_set(SPEC, config(tmp_path), session=hub, sleep=lambda s: None, log=lambda m: None)
    assert (part.parent / Path(name).name).read_bytes() == body


def test_a_file_shorter_than_the_hub_reports_is_refused_and_kept_for_resume(tmp_path):
    hub = FakeHub(tmp_path, [rows(1, 2)])
    hub.truncate_to = 200
    with pytest.raises(sync.SyncError, match="200 bytes on disk, the Hub reports"):
        sync.sync_set(SPEC, config(tmp_path), session=hub, sleep=lambda s: None, log=lambda m: None)
    assert Store(tmp_path / "data").info("tvmaze-shows") is None
    assert [p.name for p in (tmp_path / "cache" / "tvmaze-shows" / "rev1").iterdir()] == [
        "train-00000-of-00001.parquet.part"]


def test_a_file_longer_than_the_hub_reports_is_refused(tmp_path):
    hub = FakeHub(tmp_path, [rows(1)])
    name = next(iter(hub.files))
    hub.advertised_size[name] = len(hub.files[name]) - 5
    with pytest.raises(sync.SyncError):
        sync.sync_set(SPEC, config(tmp_path), session=hub, sleep=lambda s: None, log=lambda m: None)
    assert Store(tmp_path / "data").info("tvmaze-shows") is None


def test_a_checksum_mismatch_is_refused_and_the_partial_file_removed(tmp_path):
    hub = FakeHub(tmp_path, [rows(1)])
    hub.advertised_sha[next(iter(hub.files))] = "0" * 64
    with pytest.raises(sync.SyncError, match="SHA-256"):
        sync.sync_set(SPEC, config(tmp_path), session=hub, sleep=lambda s: None, log=lambda m: None)
    assert list((tmp_path / "cache" / "tvmaze-shows" / "rev1").iterdir()) == []
    assert Store(tmp_path / "data").info("tvmaze-shows") is None


def test_too_little_free_space_refuses_before_any_download(tmp_path, monkeypatch):
    hub = FakeHub(tmp_path, [rows(1)])
    monkeypatch.setattr(sync.shutil, "disk_usage", lambda path: Usage(10**9, 10**9 - 100, 100))
    with pytest.raises(sync.InsufficientSpace, match="100 bytes free"):
        sync.sync_set(SPEC, config(tmp_path), session=hub, sleep=lambda s: None, log=lambda m: None)
    assert hub.downloads() == []
    assert Store(tmp_path / "data").info("tvmaze-shows") is None


def test_the_reserve_counts_against_free_space(tmp_path, monkeypatch):
    hub = FakeHub(tmp_path, [rows(1)])
    size = sum(len(b) for b in hub.files.values())
    monkeypatch.setattr(sync.shutil, "disk_usage", lambda path: Usage(10**9, 0, size * 3))
    cfg = OfflineConfig(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", min_free=size * 3)
    with pytest.raises(sync.InsufficientSpace):
        sync.sync_set(SPEC, cfg, session=hub, sleep=lambda s: None, log=lambda m: None)
    assert hub.downloads() == []


def test_the_data_disk_is_checked_when_it_is_not_the_cache_disk(tmp_path, monkeypatch):
    hub = FakeHub(tmp_path, [rows(1)])
    monkeypatch.setattr(sync, "_device", lambda p: hash(str(p)))
    seen = []

    def usage(path):
        seen.append(Path(path))
        return Usage(10**12, 0, 10**12 if "cache" in str(path) else 1)

    monkeypatch.setattr(sync.shutil, "disk_usage", usage)
    with pytest.raises(sync.InsufficientSpace) as e:
        sync.sync_set(SPEC, config(tmp_path), session=hub, sleep=lambda s: None, log=lambda m: None)
    assert str(tmp_path / "data") in str(e.value)
    assert hub.downloads() == []


def test_a_set_without_a_directory_is_refused(tmp_path):
    with pytest.raises(sync.SyncError, match="METADATARR_OFFLINE_DIR"):
        sync.sync_set(SPEC, OfflineConfig(), session=FakeHub(tmp_path, [rows(1)]), log=lambda m: None)


def test_a_dataset_without_parquet_files_is_refused(tmp_path):
    hub = FakeHub(tmp_path, [rows(1)])
    hub.files = {}
    with pytest.raises(sync.SyncError, match="no parquet"):
        sync.hub_dataset(REPO, hub)


# -- configuration -----------------------------------------------------------------------

def test_the_layer_is_off_without_a_data_directory():
    cfg = OfflineConfig.from_env({})
    assert not cfg.enabled and cfg.fetch_dir is None


def test_config_reads_the_offline_variables(tmp_path):
    cfg = OfflineConfig.from_env({"METADATARR_OFFLINE_DIR": str(tmp_path / "d"),
                                  "METADATARR_OFFLINE_CACHE_DIR": str(tmp_path / "c"),
                                  "METADATARR_OFFLINE_MAX_AGE": "60", "METADATARR_OFFLINE_GAP": "0",
                                  "METADATARR_OFFLINE_MIN_FREE": "5"})
    assert (cfg.data_dir, cfg.fetch_dir, cfg.max_age, cfg.gap, cfg.min_free) == (tmp_path / "d", tmp_path / "c", 60.0, 0.0, 5)


def test_downloads_follow_hf_hub_cache_and_never_hf_home(tmp_path):
    cfg = OfflineConfig.from_env({"METADATARR_OFFLINE_DIR": str(tmp_path / "d"), "HF_HOME": str(tmp_path / "home"),
                                  "HF_HUB_CACHE": str(tmp_path / "hub")})
    assert cfg.fetch_dir == tmp_path / "hub" / "metadatarr-ledata"
    only_home = OfflineConfig.from_env({"METADATARR_OFFLINE_DIR": str(tmp_path / "d"),
                                        "HF_HOME": str(tmp_path / "home")})
    assert only_home.fetch_dir == tmp_path / "d" / ".parquet"


def test_the_explicit_cache_directory_beats_hf_hub_cache(tmp_path):
    cfg = OfflineConfig.from_env({"METADATARR_OFFLINE_DIR": str(tmp_path / "d"),
                                  "METADATARR_OFFLINE_CACHE_DIR": str(tmp_path / "c"),
                                  "HF_HUB_CACHE": str(tmp_path / "hub")})
    assert cfg.fetch_dir == tmp_path / "c"


# -- command line ------------------------------------------------------------------------

def run(argv, tmp_path, monkeypatch, hub=None):
    monkeypatch.delenv("METADATARR_OFFLINE_DIR", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("METADATARR_OFFLINE_CACHE_DIR", raising=False)
    return sync.main(argv, session=hub, sleep=lambda s: None)


def test_cli_lists_the_sets(tmp_path, monkeypatch, capsys):
    assert run(["--list"], tmp_path, monkeypatch) == 0
    out = capsys.readouterr().out
    assert "tvmaze-shows\tLeData/media-metadata-tvmaze-shows" in out
    for hidden in ("psychonaut", "erowid", "tripsit", "substance", "drug"):
        assert hidden not in out.lower()


def test_cli_needs_a_data_directory(tmp_path, monkeypatch, capsys):
    assert run(["--set", "tvmaze-shows"], tmp_path, monkeypatch) == 2
    assert "METADATARR_OFFLINE_DIR" in capsys.readouterr().err


def test_cli_rejects_an_unknown_set_and_an_empty_choice(tmp_path, monkeypatch, capsys):
    base = ["--data-dir", str(tmp_path / "d")]
    assert run([*base, "--set", "no-such-set"], tmp_path, monkeypatch) == 2
    assert run(base, tmp_path, monkeypatch) == 2
    assert "name a set" in capsys.readouterr().err


def test_cli_syncs_a_set_and_reports_status(tmp_path, monkeypatch, capsys):
    hub = FakeHub(tmp_path, [rows(1, 2)])
    argv = ["--data-dir", str(tmp_path / "d"), "--cache-dir", str(tmp_path / "c")]
    assert run([*argv, "--set", "tvmaze-shows", "--gap", "0"], tmp_path, monkeypatch, hub) == 0
    assert run([*argv, "--status"], tmp_path, monkeypatch) == 0
    out = capsys.readouterr().out
    assert "tvmaze-shows: 2 rows" in out and "anilist-anime: not built" in out


def test_cli_exit_code_reports_a_failed_set(tmp_path, monkeypatch, capsys):
    hub = FakeHub(tmp_path, [rows(1)])
    hub.truncate_to = 10
    argv = ["--data-dir", str(tmp_path / "d"), "--cache-dir", str(tmp_path / "c"), "--set", "tvmaze-shows"]
    assert run(argv, tmp_path, monkeypatch, hub) == 1
    assert "tvmaze-shows:" in capsys.readouterr().err
