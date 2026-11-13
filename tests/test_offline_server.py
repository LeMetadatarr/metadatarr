# SPDX-License-Identifier: Apache-2.0
"""The offline origin on the HTTP routes. The response shapes the routes had
before stay as they were; ``origin`` is added only while the layer is on."""
from __future__ import annotations

import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from mediavocab import MediaType  # noqa: E402

from metadatarr import catalog  # noqa: E402
from metadatarr.catalog import base as catalog_base  # noqa: E402
from metadatarr.offline import build, layer  # noqa: E402
from metadatarr.offline.config import OfflineConfig  # noqa: E402
from metadatarr.offline.sets import BY_NAME  # noqa: E402
from metadatarr.resolve import _cache  # noqa: E402
from metadatarr.resolve import base as resolve_base  # noqa: E402
from metadatarr.server.app import create_app  # noqa: E402
from tests._offline_fixtures import SAMPLES, write_shard  # noqa: E402
from tests.test_offline_layer import FakeSource, Live  # noqa: E402

DATASET = "LeData/media-metadata-tvmaze-shows"


@pytest.fixture
def api(tmp_path, monkeypatch):
    for name in ("tvmaze-shows", "openlibrary-books"):
        spec = BY_NAME[name]
        shard = write_shard(tmp_path / f"{name}.parquet", [SAMPLES[name]["row"]])
        build.build_set(spec, [shard], tmp_path / "data", dataset=spec.repo, revision="rev1")
    source, live = FakeSource(), Live("tvmaze")
    monkeypatch.setattr(catalog_base, "_SOURCES", {"fake": source})
    monkeypatch.setattr(resolve_base, "active_providers", lambda medium=None, signals=None: [live])
    for var in ("METADATARR_API_KEYS", "METADATARR_AUTH_EXEMPT", "METADATARR_RATE_LIMIT", "METADATARR_HTTP_CACHE"):
        monkeypatch.delenv(var, raising=False)
    layer.configure(OfflineConfig(data_dir=tmp_path / "data", max_age=0))
    _cache.cache().clear()
    catalog.reset_cache()
    yield TestClient(create_app()), source, live, tmp_path
    layer.configure(None)
    _cache.cache().clear()
    catalog.reset_cache()


def test_lookup_of_a_kind_with_children_is_live_and_says_so(api):
    client, source, _, _ = api
    r = client.get("/api/v1/lookup", params={"scheme": "tvmaze", "value": "1", "kind": "series"})
    assert source.calls == 1
    assert set(r.json()) == {"item", "providers", "errors", "truncated", "origin"}
    assert r.json()["origin"] == {"source": "live"}


def test_lookup_of_a_book_by_isbn_comes_from_the_set(api):
    client, source, _, _ = api
    r = client.get("/api/v1/lookup", params={"scheme": "isbn", "value": "978-1-57765-821-4", "kind": "book"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert source.calls == 0 and body["providers"] == ["ledata"]
    assert body["item"]["title"] == "The Picture of Dorian Gray"
    assert body["origin"] == {"source": "offline", "dataset": "LeData/media-metadata-openlibrary-books",
                              "revision": "rev1", "built_at": body["origin"]["built_at"]}


def test_refresh_on_the_route_goes_live(api):
    client, source, _, _ = api
    r = client.get("/api/v1/lookup", params={"scheme": "isbn", "value": "9781577658214", "kind": "book",
                                             "refresh": "1"})
    assert r.json()["origin"] == {"source": "live"} and source.calls == 1


def test_lookup_has_no_origin_while_the_layer_is_off(api):
    client, source, _, _ = api
    layer.configure(OfflineConfig())
    body = client.get("/api/v1/lookup", params={"scheme": "isbn", "value": "9781577658214", "kind": "book"}).json()
    assert source.calls == 1 and set(body) == {"item", "providers", "errors", "truncated"}


def test_resolve_by_id_names_the_offline_dataset(api):
    client, source, _, _ = api
    r = client.post("/api/v1/resolve", json={"ids": {"tvmaze": "1"}, "kind": "series"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert source.calls == 0
    assert body["origin"]["dataset"] == DATASET and body["origin"]["revision"] == "rev1"
    assert body["match"]["item"]["title"] == "Under the Dome" and body["providers"] == ["ledata"]
    assert body["accepted"][0]["origin"]["source"] == "offline"


def test_candidates_carry_the_origin_of_each_match(api):
    client, _, live, _ = api
    hit = client.post("/api/v1/candidates", json={"title": "Under the Dome", "medium": "episodic_series"}).json()
    assert [m["origin"]["source"] for m in hit] == ["offline"] and live.lookups == 0
    miss = client.post("/api/v1/candidates", json={"title": "Not Indexed", "medium": "episodic_series"}).json()
    assert [m["origin"] for m in miss] == [{"source": "live"}] and live.lookups == 1


def test_candidates_response_is_unchanged_while_the_layer_is_off(api):
    client, _, live, _ = api
    layer.configure(OfflineConfig())
    rows = client.post("/api/v1/candidates", json={"title": "Under the Dome", "medium": "episodic_series"}).json()
    assert live.lookups == 1 and all("origin" not in row for row in rows)


def test_enrich_names_where_the_ids_came_from_in_a_header(api):
    client, _, _, _ = api
    r = client.post("/api/v1/enrich", json={"external_ids": {"tvdb": 264492}})
    assert r.status_code == 200 and r.json()["imdb"] == "tt1553656"
    assert r.headers["X-Metadatarr-Origin"] == f"offline {DATASET}@rev1"


def test_enrich_with_nothing_offline_says_live(api):
    client, _, _, _ = api
    r = client.post("/api/v1/enrich", json={"external_ids": {"tvdb": 1}})
    assert r.headers["X-Metadatarr-Origin"] == "live"
    r = client.post("/api/v1/enrich", params={"refresh": "1"}, json={"external_ids": {"tvdb": 264492}})
    assert r.headers["X-Metadatarr-Origin"] == "live"


def test_enrich_has_no_origin_header_while_the_layer_is_off(api):
    client, _, _, _ = api
    layer.configure(OfflineConfig())
    r = client.post("/api/v1/enrich", json={"external_ids": {"tvdb": 264492}})
    assert "X-Metadatarr-Origin" not in r.headers


def test_enrich_still_rejects_malformed_ids_with_422(api):
    client, _, _, _ = api
    r = client.post("/api/v1/enrich", json={"external_ids": {"isbn_10": "12'; DROP TABLE item;--"}})
    assert r.status_code == 422 and r.json()["error"] == "invalid id"


def test_providers_list_is_unchanged(api):
    client, _, _, _ = api
    assert MediaType.MUSIC.value in {m for p in client.get("/api/v1/providers").json()["providers"] for m in p["media"]}
    assert all(p["name"] != "ledata" for p in client.get("/api/v1/providers").json()["providers"])
