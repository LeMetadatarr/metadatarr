"""HTTP cassette tests for the Wikidata provider (offline — requests patched)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from mediavocab.models.signals import Signals

from metadatarr.resolve.providers.wikidata import WikidataProvider

_SEARCH_RESPONSE = {
    "search": [
        {
            "id": "Q25188",
            "label": "Pulp Fiction",
            "description": "1994 film by Quentin Tarantino",
            "match": {"type": "label", "language": "en", "text": "Pulp Fiction"},
        }
    ]
}

_ENTITY_RESPONSE = {
    "entities": {
        "Q25188": {
            "id": "Q25188",
            "labels": {"en": {"value": "Pulp Fiction"}},
            "claims": {
                "P345": [
                    {"mainsnak": {"datavalue": {"value": "tt0110912"}}}
                ],
                "P4947": [
                    {"mainsnak": {"datavalue": {"value": "680"}}}
                ],
            },
        }
    }
}

_EMPTY_SEARCH = {"search": []}


def _make_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def test_happy_path():
    p = WikidataProvider()
    responses = [_make_response(_SEARCH_RESPONSE), _make_response(_ENTITY_RESPONSE)]
    with patch("metadatarr.resolve.providers.wikidata._SESSION.get", side_effect=responses):
        m = p.lookup(Signals(title="Pulp Fiction"))
    assert m is not None
    assert m.external_ids.wikidata == "Q25188"
    assert m.external_ids.imdb == "tt0110912"


def test_empty_results():
    p = WikidataProvider()
    with patch("metadatarr.resolve.providers.wikidata._SESSION.get", return_value=_make_response(_EMPTY_SEARCH)):
        m = p.lookup(Signals(title="NonExistentThing999"))
    assert m is None
