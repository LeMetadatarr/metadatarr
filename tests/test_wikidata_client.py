# SPDX-License-Identifier: Apache-2.0
"""Parsing of the Wikidata action API answers by the inline client."""
from __future__ import annotations

import pytest

from metadatarr.resolve.providers._wikidata_client import WikidataClient, WikidataIds


class _Response:
    def __init__(self, payload=None, status=200, bad_json=False):
        self._payload, self.status_code, self._bad_json = payload, status, bad_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class _Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return self.responses.pop(0)


def _client(*responses) -> WikidataClient:
    client = WikidataClient()
    client._session = _Session(*responses)
    return client


def _claim(value):
    return [{"mainsnak": {"datavalue": {"value": value}}}]


def _entity(qid, claims):
    return _Response({"entities": {qid: {"claims": claims}}})


def test_claims_map_to_fields_with_integers_for_numeric_ids():
    ids = _client(_entity("Q1", {
        "P345": _claim("tt0133093"), "P4947": _claim("603"), "P4835": _claim(2),
        "P212": _claim("978-0-306-40615-7"), "P436": _claim("mbid"),
    })).get_external_ids("Q1")
    assert (ids.wikidata, ids.imdb, ids.tmdb_movie, ids.tvdb) == ("Q1", "tt0133093", 603, 2)
    assert ids.isbn_13 == "978-0-306-40615-7" and ids.musicbrainz_release_group == "mbid"
    assert ids.tmdb_tv is None


def test_first_of_several_statements_wins():
    ids = _client(_entity("Q1", {"P345": _claim("tt1") + _claim("tt2")})).get_external_ids("Q1")
    assert ids.imdb == "tt1"


@pytest.mark.parametrize("claims", [
    {},
    {"P345": []},
    {"P345": [{"mainsnak": {"snaktype": "novalue"}}]},
    {"P345": [None]},
    {"P345": "tt1"},
])
def test_missing_or_malformed_claims_leave_the_field_unset(claims):
    ids = _client(_entity("Q1", claims)).get_external_ids("Q1")
    assert ids == WikidataIds(wikidata="Q1")


def test_non_numeric_value_in_integer_field_is_dropped():
    ids = _client(_entity("Q1", {"P4947": _claim("abc"), "P345": _claim("tt1")})).get_external_ids("Q1")
    assert ids.tmdb_movie is None and ids.imdb == "tt1"


def test_merged_item_is_read_from_its_target():
    response = _Response({"entities": {"Q2": {"claims": {"P345": _claim("tt9")}}},
                          "redirects": {"from": "Q1", "to": "Q2"}})
    ids = _client(response).get_external_ids("Q1")
    assert ids.wikidata == "Q1" and ids.imdb == "tt9"


def test_missing_entity_has_only_its_id():
    response = _Response({"entities": {"Q1": {"id": "Q1", "missing": ""}}})
    assert _client(response).get_external_ids("Q1") == WikidataIds(wikidata="Q1")


@pytest.mark.parametrize("response", [
    _Response(bad_json=True), _Response({"entities": {"Q1": {"claims": {"P345": _claim("tt1")}}}}, status=500), _Response([1, 2]), _Response({}),
    _Response({"entities": []}), _Response(None),
])
def test_bad_answers_give_none(response):
    assert _client(response).get_external_ids("Q1") is None


def test_empty_qid_makes_no_request():
    client = _client()
    assert client.get_external_ids("") is None and client._session.calls == []


def test_search_returns_hits_in_order():
    hits = _client(_Response({"search": [{"id": "Q1", "label": "A"}, {"id": "Q2"}]})).search("x", limit=2)
    assert [(h.id, h.label) for h in hits] == [("Q1", "A"), ("Q2", None)]


@pytest.mark.parametrize("response", [
    _Response({"search": []}), _Response({}), _Response(bad_json=True), _Response({"search": [{"id": "Q1"}]}, status=429),
    _Response({"search": "x"}), _Response({"search": [{"label": "no id"}, "x", None]}),
])
def test_search_without_usable_hits_is_empty(response):
    assert _client(response).search("x") == []


def test_search_with_empty_title_makes_no_request():
    client = _client()
    assert client.search("") == [] and client._session.calls == []


def test_search_sends_language_and_limit():
    client = _client(_Response({"search": []}))
    client.search("Dune", language="pt", limit=3)
    assert client._session.calls[0] == {"action": "wbsearchentities", "search": "Dune",
                                        "language": "pt", "format": "json", "limit": 3}


def test_reverse_lookup_uses_most_discriminating_id_first():
    client = _client(_Response({"query": {"search": [{"title": "Q42"}]}}),
                     _entity("Q42", {"P345": _claim("tt1")}))
    ids = client.enrich(WikidataIds(imdb="tt1", isbn_13="9780306406157"))
    assert client._session.calls[0]["srsearch"] == "haswbstatement:P345=tt1"
    assert client._session.calls[0]["srlimit"] == 1
    assert ids.wikidata == "Q42"


def test_reverse_lookup_falls_to_isbn_when_it_is_the_only_id():
    client = _client(_Response({"query": {"search": [{"title": "Q5"}]}}), _entity("Q5", {}))
    client.enrich(WikidataIds(isbn_10="0306406152"))
    assert client._session.calls[0]["srsearch"] == "haswbstatement:P957=0306406152"


@pytest.mark.parametrize("response", [
    _Response({"query": {"search": []}}), _Response({"query": {}}), _Response({}),
    _Response(bad_json=True), _Response({"query": {"search": [None]}}),
])
def test_reverse_lookup_without_hit_gives_none(response):
    assert _client(response).enrich(WikidataIds(imdb="tt1")) is None


def test_enrich_with_no_ids_makes_no_request():
    client = _client()
    assert client.enrich(WikidataIds()) is None and client._session.calls == []


def test_enrich_with_qid_skips_the_reverse_lookup():
    client = _client(_entity("Q7", {"P345": _claim("tt7")}))
    assert client.enrich(WikidataIds(wikidata="Q7", imdb="ttX")).imdb == "tt7"
    assert client._session.calls[0]["action"] == "wbgetentities"


def test_provider_imports_without_the_pywikidata_package():
    import subprocess
    import sys
    code = ("import sys; sys.modules['pywikidata'] = None; "
            "import metadatarr.resolve.providers.wikidata as m; "
            "from metadatarr.resolve import all_providers; "
            "assert all_providers()['wikidata'].is_available()")
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
