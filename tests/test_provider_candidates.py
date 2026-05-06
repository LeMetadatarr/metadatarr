"""Multi-candidate provider tests with stubbed HTTP."""
import pytest


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


# -----------------------------------------------------------------------------
# MusicBrainz — single search call, multiple candidates from the same payload
# -----------------------------------------------------------------------------

def test_musicbrainz_lookup_candidates(monkeypatch):
    from metadatarr.resolve import MediaType, Signals
    from metadatarr.resolve.providers.musicbrainz import MusicBrainzProvider

    payload = {"recordings": [
        {"id": "r1", "title": "Around the World", "score": 100,
         "artist-credit": [{"name": "Daft Punk",
                            "artist": {"id": "a1", "name": "Daft Punk"}}]},
        {"id": "r2", "title": "Around the World (live)", "score": 70,
         "artist-credit": [{"name": "Daft Punk",
                            "artist": {"id": "a1"}}]},
    ]}
    monkeypatch.setattr(
        "metadatarr.resolve.providers.musicbrainz.requests.get",
        lambda *a, **kw: _Resp(payload),
    )

    p = MusicBrainzProvider()
    cands = p.lookup_candidates(Signals(title="Around the World",
                                        artist="Daft Punk",
                                        medium=MediaType.MUSIC))
    assert len(cands) == 2
    assert cands[0].external_ids.musicbrainz_recording == "r1"
    assert cands[0].confidence >= cands[1].confidence


def test_musicbrainz_lookup_candidates_handles_no_results(monkeypatch):
    from metadatarr.resolve import MediaType, Signals
    from metadatarr.resolve.providers.musicbrainz import MusicBrainzProvider

    monkeypatch.setattr(
        "metadatarr.resolve.providers.musicbrainz.requests.get",
        lambda *a, **kw: _Resp({"recordings": []}),
    )
    p = MusicBrainzProvider()
    assert p.lookup_candidates(Signals(title="x", artist="y",
                                       medium=MediaType.MUSIC)) == []


# -----------------------------------------------------------------------------
# Wikidata
# -----------------------------------------------------------------------------

def test_wikidata_lookup_candidates(monkeypatch):
    from metadatarr.resolve import Signals
    from metadatarr.resolve.providers.wikidata import WikidataProvider

    search = {"search": [
        {"id": "Q1", "label": "Inception"},
        {"id": "Q2", "label": "Inception (album)"},
        {"id": "Q3", "label": "totally different"},
    ]}
    entity_q = {"entities": {
        "Q1": {"claims": {"P4947": [{"mainsnak": {"datavalue": {"value": "27205"}}}]}},
        "Q2": {"claims": {}},
        "Q3": {"claims": {}},
    }}

    def fake(url, params=None, **kw):
        action = (params or {}).get("action")
        if action == "wbsearchentities":
            return _Resp(search)
        # wbgetentities — return only the requested Q
        qid = params["ids"]
        return _Resp({"entities": {qid: entity_q["entities"][qid]}})

    monkeypatch.setattr(
        "metadatarr.resolve.providers.wikidata.requests.get",
        fake,
    )

    p = WikidataProvider()
    cands = p.lookup_candidates(Signals(title="Inception"))
    assert len(cands) == 3
    qids = [c.external_ids.wikidata for c in cands]
    assert "Q1" in qids and "Q2" in qids and "Q3" in qids
    # Q1 carries the TMDB cross-ref + best title match; should rank first.
    assert cands[0].external_ids.wikidata == "Q1"
    assert cands[0].external_ids.tmdb_movie == 27205
