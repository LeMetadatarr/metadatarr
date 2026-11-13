# SPDX-License-Identifier: Apache-2.0
"""Building a set's SQLite file from parquet shards and reading it back."""
from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("pyarrow")

from metadatarr.offline import build  # noqa: E402
from metadatarr.offline.sets import BY_NAME, SETS  # noqa: E402
from metadatarr.offline.store import Store, normalise, set_path  # noqa: E402
from tests._offline_fixtures import SAMPLES, write_shard  # noqa: E402


def built(tmp_path, name, rows=None, clock=lambda: 1000.0, revision="rev1"):
    spec = BY_NAME[name]
    shard = write_shard(tmp_path / "shards" / f"{name}.parquet", rows or [SAMPLES[name]["row"]])
    data_dir = tmp_path / "data"
    info = build.build_set(spec, [shard], data_dir, dataset=spec.repo, revision=revision, clock=clock)
    return info, Store(data_dir)


def test_every_set_has_a_sample():
    assert sorted(SAMPLES) == sorted(s.name for s in SETS)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_set_maps_its_real_columns(tmp_path, name):
    expected = SAMPLES[name]["expected"]
    info, store = built(tmp_path, name)
    assert info.rows == 1
    first_id = next(iter(expected["ids"].items()))
    for row in (store.find_ids(name, dict([first_id])), *store.find_name(name, SAMPLES[name]["query"])):
        assert row is not None, name
        assert row.title == expected["title"]
        assert row.year == expected["year"]
        assert row.kind == expected["kind"]
        assert row.ids == expected["ids"]
        assert row.data.get("artist") == expected.get("artist")
        assert row.data.get("overview") == expected.get("overview")
        assert row.data.get("runtime_min") == expected.get("runtime")
        assert row.data.get("poster_url") == expected.get("poster")
        for key, value in expected["extra"].items():
            assert row.data["extra"][key] == value


def test_meta_records_dataset_revision_rows_and_build_time(tmp_path):
    info, store = built(tmp_path, "tvmaze-shows", clock=lambda: 1234.5, revision="abc123")
    assert (info.dataset, info.revision, info.rows, info.built_at) == (
        "LeData/media-metadata-tvmaze-shows", "abc123", 1, 1234.5)
    assert store.info("tvmaze-shows") == info
    assert info.origin() == {"source": "offline", "dataset": "LeData/media-metadata-tvmaze-shows",
                             "revision": "abc123", "built_at": "1970-01-01T00:20:34Z"}


def test_file_is_wal_with_indexes_on_the_lookup_keys(tmp_path):
    built(tmp_path, "openlibrary-books")
    assert not (tmp_path / "data" / "openlibrary-books.sqlite-wal").exists()
    conn = sqlite3.connect(set_path(tmp_path / "data", "openlibrary-books"))
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    plan = conn.execute("EXPLAIN QUERY PLAN SELECT pk FROM ext_id WHERE field = ? AND value = ?",
                        ("olid", "OL1W")).fetchall()
    assert any("PRIMARY KEY" in str(step) for step in plan)
    plan = conn.execute("EXPLAIN QUERY PLAN SELECT pk FROM item WHERE norm = ?", ("x",)).fetchall()
    assert any("item_norm" in str(step) for step in plan)


def test_equal_names_come_best_ranked_first(tmp_path):
    base = SAMPLES["jikan-manga"]["row"]
    rows = [{**base, "mal_id": "10", "title": "Monster", "members": 5},
            {**base, "mal_id": "11", "title": "monster", "members": 900},
            {**base, "mal_id": "12", "title": "Monster!", "members": 50}]
    _, store = built(tmp_path, "jikan-manga", rows=rows)
    assert [r.ids["mal_id"] for r in store.find_name("jikan-manga", "MONSTER")] == ["11", "12", "10"]


def test_rows_without_a_title_are_skipped_and_counted(tmp_path):
    base = SAMPLES["tvmaze-shows"]["row"]
    info, store = built(tmp_path, "tvmaze-shows", rows=[base, {**base, "tvmaze_id": "2", "name": None},
                                                         {**base, "tvmaze_id": "3", "name": " "}])
    assert info.rows == 1
    assert store.find_ids("tvmaze-shows", {"tvmaze": "2"}) is None
    meta = dict(sqlite3.connect(set_path(tmp_path / "data", "tvmaze-shows")).execute("SELECT * FROM meta"))
    assert meta["skipped"] == "2"


def test_shard_without_an_id_column_is_refused(tmp_path):
    row = {k: v for k, v in SAMPLES["tvmaze-shows"]["row"].items() if k != "thetvdb_id"}
    shard = write_shard(tmp_path / "s.parquet", [row])
    with pytest.raises(build.BuildError, match="thetvdb_id"):
        build.build_set(BY_NAME["tvmaze-shows"], [shard], tmp_path / "data", dataset="d", revision="r")
    assert not set_path(tmp_path / "data", "tvmaze-shows").exists()


def test_failed_rebuild_leaves_the_old_file_intact(tmp_path, monkeypatch):
    _, store = built(tmp_path, "tvmaze-shows", revision="old")
    path = set_path(tmp_path / "data", "tvmaze-shows")
    before = path.read_bytes()
    row = {**SAMPLES["tvmaze-shows"]["row"], "tvmaze_id": "99", "name": "Replacement"}
    shard = write_shard(tmp_path / "second.parquet", [row, {**row, "tvmaze_id": "100"}])
    calls = []
    real = build.convert

    def explode_on_second_row(spec, rec):
        calls.append(rec["tvmaze_id"])
        if len(calls) == 2:
            raise RuntimeError("disk fell over")
        return real(spec, rec)

    monkeypatch.setattr(build, "convert", explode_on_second_row)
    with pytest.raises(RuntimeError, match="disk fell over"):
        build.build_set(BY_NAME["tvmaze-shows"], [shard], tmp_path / "data", dataset="d", revision="new")
    assert calls == ["99", "100"]
    assert path.read_bytes() == before
    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == ["tvmaze-shows.sqlite"]
    assert store.find_ids("tvmaze-shows", {"tvmaze": "1"}).title == "Under the Dome"
    assert store.info("tvmaze-shows").revision == "old"


def test_successful_rebuild_replaces_the_file_and_readers_follow(tmp_path):
    _, store = built(tmp_path, "tvmaze-shows", revision="old")
    assert store.find_ids("tvmaze-shows", {"tvmaze": "1"}) is not None
    row = {**SAMPLES["tvmaze-shows"]["row"], "tvmaze_id": "99", "name": "Replacement"}
    shard = write_shard(tmp_path / "second.parquet", [row])
    build.build_set(BY_NAME["tvmaze-shows"], [shard], tmp_path / "data", dataset="d", revision="new")
    assert store.info("tvmaze-shows").revision == "new"
    assert store.find_ids("tvmaze-shows", {"tvmaze": "1"}) is None
    assert store.find_name("tvmaze-shows", "replacement")[0].ids["tvmaze"] == "99"


def test_a_shard_that_yields_fewer_rows_than_it_declares_is_refused(tmp_path, monkeypatch):
    import pyarrow.parquet as pq

    shard = write_shard(tmp_path / "s.parquet", [SAMPLES["tvmaze-shows"]["row"]] * 3)

    class Lossy:
        def __init__(self, path):
            self._real = pq.ParquetFile(path)
            self.schema_arrow, self.metadata = self._real.schema_arrow, self._real.metadata

        def iter_batches(self, **kwargs):
            for batch in self._real.iter_batches(**kwargs):
                yield batch.slice(0, batch.num_rows - 1)

    class FakePq:
        ParquetFile = Lossy

    monkeypatch.setattr(build, "_parquet", lambda: FakePq)
    with pytest.raises(build.BuildError, match="read 2 rows, shards declare 3"):
        build.build_set(BY_NAME["tvmaze-shows"], [shard], tmp_path / "data", dataset="d", revision="r")
    assert not set_path(tmp_path / "data", "tvmaze-shows").exists()


# -- hostile input -----------------------------------------------------------------------

INJECTIONS = ["x'); DROP TABLE item; --", "' OR '1'='1", "1; DELETE FROM ext_id", '" OR ""="', "%", "_", "\x00",
              "Robert'); DROP TABLE meta;--"]


@pytest.mark.parametrize("text", INJECTIONS)
def test_names_and_ids_with_sql_in_them_are_data(tmp_path, text):
    row = {**SAMPLES["tvmaze-shows"]["row"], "tvmaze_id": "7", "name": text, "imdb_id": text}
    _, store = built(tmp_path, "tvmaze-shows", rows=[row, SAMPLES["tvmaze-shows"]["row"]])
    found = store.find_ids("tvmaze-shows", {"imdb": text})
    assert found is not None and found.title == text
    if normalise(text):
        assert [r.title for r in store.find_name("tvmaze-shows", text)] == [text]
    # none of it reaches the schema or the other row
    assert store.find_ids("tvmaze-shows", {"tvmaze": "1"}).title == "Under the Dome"
    assert store.find_ids("tvmaze-shows", {"imdb": text + "'"}) is None
    assert store.find_name("tvmaze-shows", "%") == []
    tables = {r[0] for r in sqlite3.connect(set_path(tmp_path / "data", "tvmaze-shows")).execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == {"item", "ext_id", "alias", "meta"}


def test_a_field_name_is_never_taken_from_the_caller(tmp_path):
    _, store = built(tmp_path, "tvmaze-shows")
    assert store.find_ids("tvmaze-shows", {"imdb = 'x' OR 1=1 --": "tt1553656"}) is None
    assert store.find_ids("tvmaze-shows", {"imdb": "tt1553656' OR '1'='1"}) is None


# -- damaged files -----------------------------------------------------------------------

def test_missing_file_is_absent_not_an_error(tmp_path):
    store = Store(tmp_path)
    assert store.info("tvmaze-shows") is None
    assert store.find_ids("tvmaze-shows", {"imdb": "tt1"}) is None
    assert store.find_name("tvmaze-shows", "x") == []


@pytest.mark.parametrize("damage", ["garbage", "truncated", "empty", "no_meta", "wrong_schema", "no_tables"])
def test_damaged_file_is_absent_not_an_error(tmp_path, damage):
    _, store = built(tmp_path, "tvmaze-shows")
    store.close()
    path = set_path(tmp_path / "data", "tvmaze-shows")
    good = path.read_bytes()
    if damage == "garbage":
        path.write_bytes(b"this is not a database" * 50)
    elif damage == "truncated":
        path.write_bytes(good[: len(good) // 3])
    elif damage == "empty":
        path.write_bytes(b"")
    else:
        path.unlink()
        conn = sqlite3.connect(path)
        if damage == "no_meta":
            conn.executescript("CREATE TABLE item (pk INTEGER PRIMARY KEY); CREATE TABLE meta (key, value);")
        elif damage == "wrong_schema":
            conn.executescript("CREATE TABLE meta (key, value); INSERT INTO meta VALUES ('schema', '999');")
        else:
            conn.executescript("CREATE TABLE unrelated (a);")
        conn.commit()
        conn.close()
    fresh = Store(tmp_path / "data")
    assert fresh.info("tvmaze-shows") is None
    assert fresh.find_ids("tvmaze-shows", {"imdb": "tt1553656"}) is None
    assert fresh.find_name("tvmaze-shows", "under the dome") == []


def test_a_file_that_fails_mid_read_is_absent_not_an_error(tmp_path):
    _, store = built(tmp_path, "tvmaze-shows")
    conn = sqlite3.connect(set_path(tmp_path / "data", "tvmaze-shows"))
    conn.execute("UPDATE item SET data = 'not json'")
    conn.commit()
    conn.close()
    assert Store(tmp_path / "data").find_name("tvmaze-shows", "under the dome") == []


def test_staleness_is_a_configured_age_with_zero_meaning_never(tmp_path):
    info, _ = built(tmp_path, "tvmaze-shows", clock=lambda: 1000.0)
    assert not info.stale(100, 1100.0)
    assert info.stale(100, 1100.5)
    assert not info.stale(0, 10**12)


def test_a_file_from_another_schema_version_is_absent_and_warned_about_once(tmp_path, caplog):
    _, store = built(tmp_path, "tvmaze-shows")
    store.close()
    conn = sqlite3.connect(set_path(tmp_path / "data", "tvmaze-shows"))
    conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema'")
    conn.commit()
    conn.close()
    fresh = Store(tmp_path / "data")
    with caplog.at_level("WARNING", logger="metadatarr.offline"):
        assert fresh.info("tvmaze-shows") is None
        assert fresh.find_name("tvmaze-shows", "under the dome") == []
        assert fresh.find_ids("tvmaze-shows", {"imdb": "tt1553656"}) is None
    warnings = [r for r in caplog.records if r.name == "metadatarr.offline"]
    assert len(warnings) == 1 and "schema 99" in warnings[0].getMessage()
