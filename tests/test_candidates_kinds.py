# SPDX-License-Identifier: Apache-2.0
"""``POST /api/v1/candidates`` with a ``kind``: the fan-out to providers that
declare a search kind, the media-kind path, and the ``search_kinds``
capability. Offline: the registry holds only the stub providers below."""
from __future__ import annotations

from typing import List, Optional

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from mediavocab import MediaType  # noqa: E402
from mediavocab.models import ExternalIds  # noqa: E402
from mediavocab.models.signals import Signals  # noqa: E402

from metadatarr.resolve import base as resolve_base  # noqa: E402
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, SearchCandidate, consolidate  # noqa: E402
from metadatarr.resolve.entities import EntityRole, ProviderEntity  # noqa: E402
from metadatarr.server.app import create_app  # noqa: E402
from metadatarr.server.config import ServerConfig  # noqa: E402

GENRE = "zz_people_genre"


class PeopleFake(MetadataProvider):
    """Answers performer and studio searches, only for the caller's genre."""

    name = "people_fake"
    genre_filter = {GENRE}
    search_kinds = frozenset({"performer", "studio"})

    def __init__(self):
        self.asked: List[tuple] = []

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return None

    def search(self, kind: str, signals: Signals) -> List[SearchCandidate]:
        self.asked.append((kind, signals.title))
        if signals.title == "boom":
            raise RuntimeError("upstream exploded")
        if kind == "performer":
            return [
                SearchCandidate(provider=self.name, confidence=0.9, kind="performer",
                                title="Placeholder Person", ids={"people_fake_id": "p-1"},
                                poster="https://img.invalid/p-1.jpg", overview="A placeholder.",
                                aliases=["P. Person"], medium="fake_medium",
                                attributes={"gender": "placeholder_gender"}),
                SearchCandidate(provider=self.name, confidence=0.4, kind="studio",
                                title="Wrong Kind Row", ids={"people_fake_studio_id": "s-9"}),
            ]
        return [SearchCandidate(provider=self.name, confidence=0.8, kind="studio",
                                title="Placeholder Studio", ids={"people_fake_studio_id": "s-1"})]


class OtherPeople(MetadataProvider):
    """A second performer source, ungated, ranked below ``people_fake``."""

    name = "other_people_fake"
    search_kinds = frozenset({"performer"})

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return None

    def search(self, kind: str, signals: Signals) -> List[SearchCandidate]:
        return [SearchCandidate(provider=self.name, confidence=0.6, kind=kind,
                                title="Placeholder Person", ids={"other_id": "o-1"})]


class TitleFake(MetadataProvider):
    """A title provider: answers the title fan-out and declares ``clip`` search
    through the default ``search`` (its title candidates)."""

    name = "title_fake"
    media = {MediaType.MOVIE, MediaType.SHORT_FILM}
    search_kinds = frozenset({"clip"})

    def __init__(self):
        self.seen: List[Signals] = []

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        self.seen.append(signals)
        return ProviderMatch(
            provider=self.name, confidence=0.7,
            signals=Signals(title="Placeholder Clip", year=2001, medium=MediaType.SHORT_FILM),
            external_ids=ExternalIds(tmdb_movie=42, extra={"title_fake_clip_id": "c-1"}),
        )


@pytest.fixture()
def fakes(monkeypatch):
    people, other, title = PeopleFake(), OtherPeople(), TitleFake()
    monkeypatch.setattr(resolve_base, "_REGISTRY",
                        {p.name: p for p in (people, other, title)})
    from metadatarr.resolve._cache import cache
    cache().clear()
    yield people, other, title
    cache().clear()


def _post(body):
    client = TestClient(create_app(ServerConfig()))
    resp = client.post("/api/v1/candidates", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_performer_search_reaches_only_declaring_providers(fakes):
    people, _, title = fakes
    rows = _post({"title": "Placeholder Person", "kind": "performer", "content_genres": [GENRE]})
    assert rows == [
        {"provider": "people_fake", "confidence": 0.9, "kind": "performer",
         "title": "Placeholder Person", "year": None, "ids": {"people_fake_id": "p-1"},
         "poster": "https://img.invalid/p-1.jpg", "overview": "A placeholder.",
         "aliases": ["P. Person"], "medium": "fake_medium",
         "attributes": {"gender": "placeholder_gender"}},
        {"provider": "other_people_fake", "confidence": 0.6, "kind": "performer",
         "title": "Placeholder Person", "year": None, "ids": {"other_id": "o-1"},
         "poster": None, "overview": None, "aliases": [], "medium": None, "attributes": {}},
    ]
    assert people.asked == [("performer", "Placeholder Person")]
    assert title.seen == []


def test_genre_gated_provider_is_not_asked_without_its_genre(fakes):
    people, _, _ = fakes
    rows = _post({"title": "Placeholder Person", "kind": "performer"})
    assert [r["provider"] for r in rows] == ["other_people_fake"]
    assert people.asked == []


def test_studio_search(fakes):
    rows = _post({"title": "Placeholder Studio", "kind": "Studio", "content_genres": [GENRE]})
    assert [(r["kind"], r["title"], r["ids"]) for r in rows] == [
        ("studio", "Placeholder Studio", {"people_fake_studio_id": "s-1"})]


def test_a_raising_provider_does_not_sink_the_search(fakes):
    people, _, _ = fakes
    rows = _post({"title": "boom", "kind": "performer", "content_genres": [GENRE]})
    assert people.asked == [("performer", "boom")]
    assert [r["provider"] for r in rows] == ["other_people_fake"]


def test_kind_nobody_declares_is_an_empty_list(fakes):
    _, _, title = fakes
    assert _post({"title": "anything", "kind": "nobody_kind"}) == []
    assert title.seen == []


def test_default_search_flattens_title_candidates(fakes):
    rows = _post({"title": "Placeholder Clip", "kind": "clip"})
    assert rows == [{"provider": "title_fake", "confidence": 0.7, "kind": "clip",
                     "title": "Placeholder Clip", "year": 2001,
                     "ids": {"tmdb_movie": "42", "title_fake_clip_id": "c-1"},
                     "poster": None, "overview": None, "aliases": [], "medium": "short_film",
                     "attributes": {}}]


def test_media_kind_defaults_the_medium_and_adds_candidate_fields(fakes):
    _, _, title = fakes
    rows = _post({"title": "Placeholder Clip", "kind": "movie"})
    assert title.seen[-1].medium == MediaType.MOVIE
    (row,) = rows
    assert row["signals"]["title"] == "Placeholder Clip"
    assert row["external_ids"]["tmdb_movie"] == 42
    assert row["kind"] == "movie" and row["title"] == "Placeholder Clip" and row["year"] == 2001
    assert row["ids"] == {"tmdb_movie": "42", "title_fake_clip_id": "c-1"}


def test_request_without_kind_is_unchanged(fakes):
    rows = _post({"title": "Placeholder Clip", "medium": "movie"})
    (row,) = rows
    assert set(row) == {"provider", "confidence", "signals", "external_ids", "relations", "variants"}


def test_providers_list_search_kinds(fakes):
    client = TestClient(create_app(ServerConfig()))
    caps = {p["name"]: p["capabilities"] for p in client.get("/api/v1/providers").json()["providers"]}
    assert caps["people_fake"]["search_kinds"] == ["performer", "studio"]
    assert caps["title_fake"]["search_kinds"] == ["clip"]
    assert caps["other_people_fake"]["search_kinds"] == ["performer"]
    assert caps["people_fake"]["lookup"] == {}


def _cast_match(provider, attributes):
    actor = ProviderEntity(role=EntityRole.ACTOR, name="Placeholder Person",
                           external_ids=ExternalIds(extra={"people_fake_id": "p-1"}),
                           attributes=attributes)
    return ProviderMatch(provider=provider, confidence=0.9 if provider == "a" else 0.8,
                         signals=Signals(title="Placeholder Clip"),
                         relations={EntityRole.ACTOR: [actor]})


def test_entity_attributes_merge_across_providers_first_writer_wins():
    result = consolidate([
        _cast_match("a", {"gender": "first_value"}),
        _cast_match("b", {"gender": "second_value", "ethnicity": "placeholder_ethnicity"}),
    ], Signals(title="Placeholder Clip"))
    (actor,) = result.relations[EntityRole.ACTOR]
    assert actor.attributes == {"gender": "first_value", "ethnicity": "placeholder_ethnicity"}
    assert result.model_dump(mode="json")["relations"]["actor"][0]["attributes"] == actor.attributes


def _resolve_refs(node, components):
    if isinstance(node, dict):
        if "$ref" in node:
            return _resolve_refs(components[node["$ref"].rsplit("/", 1)[-1]], components)
        return {k: _resolve_refs(v, components) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(v, components) for v in node]
    return node


@pytest.mark.parametrize("body", [
    {"title": "Placeholder Clip", "medium": "movie"},
    {"title": "Placeholder Clip", "kind": "movie"},
    {"title": "Placeholder Clip", "kind": "clip"},
    {"title": "Placeholder Person", "kind": "performer", "content_genres": [GENRE]},
    {"title": "Placeholder Studio", "kind": "studio", "content_genres": [GENRE]},
])
def test_every_row_kind_validates_against_the_published_schema(fakes, body):
    from jsonschema import validate
    client = TestClient(create_app(ServerConfig()))
    spec = client.get("/openapi.json").json()
    schema = spec["paths"]["/api/v1/candidates"]["post"]["responses"]["200"]["content"][
        "application/json"]["schema"]
    schema = _resolve_refs(schema, spec["components"]["schemas"])
    rows = client.post("/api/v1/candidates", json=body).json()
    assert rows
    validate(rows, schema)


class SceneFake(MetadataProvider):
    """Returns its rows in ascending confidence, against the ranking order."""

    name = "scene_fake"
    search_kinds = frozenset({"scene"})

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return None

    def search(self, kind: str, signals: Signals) -> List[SearchCandidate]:
        return [SearchCandidate(provider=self.name, confidence=c, kind=kind,
                                title=f"Placeholder Scene {c}")
                for c in (0.4, 0.95, 0.5)]


def test_kind_rows_are_sorted_by_confidence(monkeypatch):
    monkeypatch.setattr(resolve_base, "_REGISTRY", {"scene_fake": SceneFake()})
    from metadatarr.resolve._cache import cache
    cache().clear()
    rows = _post({"title": "Placeholder Scene", "kind": "scene"})
    cache().clear()
    assert [r["confidence"] for r in rows] == [0.95, 0.5, 0.4]
