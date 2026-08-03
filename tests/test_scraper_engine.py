"""Offline tests for the scraper engine — no network.

Fake Sources drive the engine loop directly and a fake ``get_json`` exercises
:class:`PaginatedJSONSource`, so every guarantee (resume, dedup, cursor
advance, limit, short-page termination) is checked deterministically.
"""
from __future__ import annotations

import json

import pytest

from metadatarr.scrapers._checkpoint import count_rows, load_checkpoint
from metadatarr.scrapers.engine import (
    PaginatedJSONSource,
    PartitionedJSONSource,
    Source,
    all_sources,
    deep_get,
    get_source,
    register,
    run_cli,
)


class _FakePagedSource(Source):
    """Yields three fixed pages of two rows each, then stops."""

    name = "fake_paged"
    id_field = "id"
    default_delay = 0.0

    PAGES = {
        0: ([{"id": "1", "v": "a"}, {"id": "2", "v": "b"}], 1),
        1: ([{"id": "3", "v": "c"}, {"id": "4", "v": "d"}], 2),
        2: ([{"id": "5", "v": "e"}, {"id": "6", "v": "f"}], None),
    }

    def __init__(self, **kw):
        super().__init__(**kw)
        self.fetched = []

    def fetch(self, cursor):
        self.fetched.append(cursor)
        return self.PAGES[cursor]


def _read_rows(output_dir, name):
    path = output_dir / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_runs_all_pages_and_writes_rows(tmp_path):
    src = _FakePagedSource()
    total = src.run(tmp_path)
    assert total == 6
    rows = _read_rows(tmp_path, "fake_paged")
    assert [r["id"] for r in rows] == ["1", "2", "3", "4", "5", "6"]
    assert src.fetched == [0, 1, 2]


def test_checkpoint_persists_next_cursor(tmp_path):
    _FakePagedSource().run(tmp_path)
    ckpt = load_checkpoint("fake_paged", tmp_path)
    # last page's next_cursor is None -> harvest complete
    assert ckpt["cursor"] is None
    assert ckpt["total"] == 6


def test_resume_skips_already_written_rows(tmp_path):
    # First run stops after the dataset reaches 2 rows.
    first = _FakePagedSource()
    first.run(tmp_path, limit=2)
    assert count_rows("fake_paged", tmp_path) == 2

    # Second run resumes from the saved cursor and appends the rest, with no
    # duplicates even though ids could overlap.
    second = _FakePagedSource()
    total = second.run(tmp_path)
    assert total == 6
    rows = _read_rows(tmp_path, "fake_paged")
    ids = [r["id"] for r in rows]
    assert ids == ["1", "2", "3", "4", "5", "6"]
    assert len(ids) == len(set(ids))


def test_dedup_drops_repeat_ids_within_a_run(tmp_path):
    class _Dupes(Source):
        name = "dupes"
        id_field = "id"
        default_delay = 0.0

        def fetch(self, cursor):
            if cursor == 0:
                return [{"id": "x"}, {"id": "y"}], 1
            return [{"id": "y"}, {"id": "z"}], None  # 'y' repeats

    total = _Dupes().run(tmp_path)
    assert total == 3
    assert [r["id"] for r in _read_rows(tmp_path, "dupes")] == ["x", "y", "z"]


def test_no_id_field_keeps_everything(tmp_path):
    class _NoId(Source):
        name = "noid"
        id_field = ""
        default_delay = 0.0

        def fetch(self, cursor):
            if cursor == 0:
                return [{"v": 1}, {"v": 1}], None
            return [], None

    assert _NoId().run(tmp_path) == 2


def test_deep_get():
    obj = {"meta": {"results": {"total": 7}}}
    assert deep_get(obj, "meta.results.total") == 7
    assert deep_get(obj, "meta.missing.total") is None
    assert deep_get({"a": 1}, "a.b") is None


class _FakeJSONSource(PaginatedJSONSource):
    name = "fake_json"
    id_field = "id"
    default_delay = 0.0
    base = "https://example.test/api"
    results_key = "data.items"
    page_size = 2

    def map_row(self, record):
        return {"id": str(record["id"]), "title": record["name"].strip()}


def test_paginated_json_source_offset_walk(tmp_path, monkeypatch):
    # A two-page API: full page (2) then a short page (1) -> stop.
    pages = {
        0: {"data": {"items": [{"id": 1, "name": " A "}, {"id": 2, "name": "B"}]}},
        2: {"data": {"items": [{"id": 3, "name": "C"}]}},
    }
    calls = []

    def fake_get_json(self, url, params=None):
        calls.append((url, dict(params)))
        return pages[params["skip"]]

    monkeypatch.setattr(_FakeJSONSource, "get_json", fake_get_json, raising=True)

    total = _FakeJSONSource().run(tmp_path)
    assert total == 3
    rows = _read_rows(tmp_path, "fake_json")
    assert rows == [
        {"id": "1", "title": "A"},
        {"id": "2", "title": "B"},
        {"id": "3", "title": "C"},
    ]
    # offset advanced by page_size and stopped after the short page
    assert [c[1]["skip"] for c in calls] == [0, 2]
    assert calls[0][0] == "https://example.test/api"


def test_map_row_can_drop_records(tmp_path, monkeypatch):
    class _Filtering(_FakeJSONSource):
        name = "filtering"

        def map_row(self, record):
            if record["name"] == "skip":
                return None
            return {"id": str(record["id"]), "title": record["name"]}

    page = {"data": {"items": [{"id": 1, "name": "keep"}, {"id": 2, "name": "skip"}]}}
    monkeypatch.setattr(_Filtering, "get_json",
                        lambda self, url, params=None: page if params["skip"] == 0
                        else {"data": {"items": []}}, raising=True)
    total = _Filtering().run(tmp_path)
    assert total == 1
    assert [r["id"] for r in _read_rows(tmp_path, "filtering")] == ["1"]


def test_registry_and_dispatch():
    @register
    class _Reg(Source):
        name = "reg_demo"
        id_field = "id"
        default_delay = 0.0

        def fetch(self, cursor):
            return [], None

    assert get_source("reg_demo") is _Reg
    assert "reg_demo" in all_sources()
    with pytest.raises(KeyError):
        get_source("does_not_exist")


def test_source_without_name_rejected():
    class _Nameless(Source):
        def fetch(self, cursor):
            return [], None

    with pytest.raises(ValueError):
        _Nameless()


def test_run_cli_end_to_end(tmp_path):
    rc = run_cli(_FakePagedSource, ["--output", str(tmp_path), "--delay", "0"])
    assert rc == 0
    assert count_rows("fake_paged", tmp_path) == 6


class _FakePartitioned(PartitionedJSONSource):
    name = "fake_part"
    id_field = "id"
    default_delay = 0.0
    base = "https://example.test/search"
    results_key = "docs"
    page_size = 2

    def partitions(self):
        return [{"subject": "a"}, {"subject": "b"}]

    def map_row(self, record):
        return {"id": str(record["id"])}


def test_partitioned_source_walks_every_seed_then_stops(tmp_path, monkeypatch):
    # seed a: one full page (2) then a short page (1) -> exhausted
    # seed b: one short page (1) -> exhausted immediately
    responses = {
        ("a", 0): {"docs": [{"id": 1}, {"id": 2}]},
        ("a", 2): {"docs": [{"id": 3}]},
        ("b", 0): {"docs": [{"id": 4}]},
    }
    seen_calls = []

    def fake_get_json(self, url, params=None):
        seen_calls.append((params["subject"], params["skip"]))
        return responses[(params["subject"], params["skip"])]

    monkeypatch.setattr(_FakePartitioned, "get_json", fake_get_json, raising=True)
    total = _FakePartitioned().run(tmp_path)
    assert total == 4
    assert [r["id"] for r in _read_rows(tmp_path, "fake_part")] == ["1", "2", "3", "4"]
    # walked seed a's offsets, then seed b
    assert seen_calls == [("a", 0), ("a", 2), ("b", 0)]


def test_partitioned_source_resumes_mid_seed(tmp_path, monkeypatch):
    responses = {
        ("a", 0): {"docs": [{"id": 1}, {"id": 2}]},
        ("a", 2): {"docs": [{"id": 3}]},
        ("b", 0): {"docs": [{"id": 4}]},
    }
    monkeypatch.setattr(_FakePartitioned, "get_json",
                        lambda self, url, params=None: responses[(params["subject"], params["skip"])],
                        raising=True)
    # Stop after 2 rows (mid seed a), then resume.
    _FakePartitioned().run(tmp_path, limit=2)
    ck = load_checkpoint("fake_part", tmp_path)
    assert ck["cursor"] == {"part": 0, "skip": 2}
    _FakePartitioned().run(tmp_path)
    assert [r["id"] for r in _read_rows(tmp_path, "fake_part")] == ["1", "2", "3", "4"]


def test_http_retry_then_success(tmp_path, monkeypatch):
    import metadatarr.scrapers.engine as eng

    monkeypatch.setattr(eng.time if hasattr(eng, "time") else __import__("time"),
                        "sleep", lambda s: None, raising=False)

    class _Flaky(PaginatedJSONSource):
        name = "flaky"
        id_field = "id"
        default_delay = 0.0
        base = "https://x.test"
        results_key = "items"
        page_size = 5
        backoff_base = 0.0

        def map_row(self, record):
            return {"id": str(record["id"])}

    attempts = {"n": 0}

    class _Resp:
        def __init__(self, data): self._data = data
        def raise_for_status(self): pass
        def json(self): return self._data

    def flaky_get(url, params=None, timeout=None):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("boom")
        return _Resp({"items": [{"id": 1}]})

    src = _Flaky()
    monkeypatch.setattr(src, "session", lambda: type("S", (), {"get": staticmethod(flaky_get)})())
    total = src.run(tmp_path)
    assert total == 1
    assert attempts["n"] == 3  # failed twice, succeeded on the third
