"""Row-schema equivalence tests for the wikidata/pubchem/who_inn/chembl/
dailymed/wiktionary/listennotes/anilist_crawl batch migrated onto the engine.

These lock the exact flat-row shape each scraper emits against a realistic
upstream sample, mirroring test_scrapers_migrated.py / test_scrapers_batch1.py
/ test_scrapers_batch2.py.
"""
from __future__ import annotations

from metadatarr.scrapers.engine import all_sources
from metadatarr.scrapers.anilist_crawl import AniListCrawlSource
from metadatarr.scrapers.listennotes_podcasts import (
    ListenNotesPodcastsSource,
    _parse_detail,
    _urls_from_listing,
    _ln_id_from_url,
)
from metadatarr.scrapers.wikidata_sparql import WikidataEntitiesSource, QUERIES, QUERY_INDEX
from metadatarr.scrapers.pubchem import PubChemCompoundsSource
from metadatarr.scrapers.who_inn import WhoInnSource, NAME_TYPES
from metadatarr.scrapers.chembl_drugs import ChemblDrugsSource
from metadatarr.scrapers.dailymed_names import DailyMedNamesSource
from metadatarr.scrapers.wiktionary_pronunciations import WiktionaryPronunciationsSource, _extract_ipa


def test_anilist_crawl_map_row_schema():
    src = AniListCrawlSource()
    m = {
        "id": 1, "idMal": 21,
        "title": {"romaji": "Cowboy Bebop", "english": "Cowboy Bebop", "native": "カウボーイビバップ"},
        "type": "ANIME", "format": "TV", "status": "FINISHED",
        "episodes": 26, "duration": 24, "chapters": None, "volumes": None,
        "countryOfOrigin": "JP", "source": "ORIGINAL",
        "startDate": {"year": 1998, "month": 4, "day": 3},
        "endDate": {"year": 1999, "month": 4, "day": 24},
        "season": "SPRING", "seasonYear": 1998,
        "genres": ["Action"],
        "tags": [{"name": "Space", "isAdult": False}],
        "studios": {"nodes": [{"id": 14, "name": "Sunrise"}]},
        "averageScore": 86, "popularity": 100000, "favourites": 5000, "isAdult": False,
    }
    row = src.map_row(m)
    assert row["anilist_id"] == 1
    assert row["start_date"] == "1998-04-03"
    assert row["tags"] == ["Space"]
    assert set(row) == {
        "anilist_id", "mal_id", "title_romaji", "title_english", "title_native",
        "type", "format", "status", "episodes", "duration", "chapters", "volumes",
        "country_of_origin", "source_material", "start_date", "end_date", "season",
        "season_year", "genres", "tags", "studios", "studio_ids", "average_score",
        "popularity", "favourites", "is_adult",
    }


def test_anilist_crawl_fetch_walks_id_chunks_and_stops_at_max_id():
    src = AniListCrawlSource()
    src.max_id = 600
    src.throttle.wait = lambda: None

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200
            self.headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    class FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            ids = json["variables"]["ids"]
            media = [{"id": ids[0]}] if ids else []
            return FakeResp({"data": {"Page": {"pageInfo": {"hasNextPage": False}, "media": media}}})

    src._session = FakeSession()
    rows, cursor = src.fetch(1)
    assert len(rows) == 1
    assert cursor == 501

    rows, cursor = src.fetch(cursor)
    assert cursor is None


def test_listennotes_parse_detail_extracts_jsonld():
    html = (
        '<script type="application/ld+json">'
        '{"@type": "PodcastSeries", "name": "The Daily", "description": "News podcast",'
        ' "image": {"url": "http://img"}, "author": {"name": "NYT"}, "inLanguage": "en",'
        ' "url": "http://site", "genre": ["News"]}'
        '</script>'
    )
    row = _parse_detail(html, "https://www.listennotes.com/podcasts/the-daily-abc123def4/")
    assert row["ln_id"] == "daily-abc123def4"
    assert row["title"] == "The Daily"
    assert row["author"] == "NYT"
    assert row["genres"] == ["News"]
    assert row["entity_type"] == "podcast"
    assert set(row) == {
        "ln_id", "ln_url", "title", "author", "description", "image", "language",
        "genres", "episode_count", "listen_score", "global_rank", "website", "entity_type",
    }


def test_listennotes_parse_detail_drops_without_title():
    assert _parse_detail("<html></html>", "https://www.listennotes.com/podcasts/x-abc123def4/") is None


def test_listennotes_urls_from_listing_itemlist():
    html = (
        '<script type="application/ld+json">'
        '{"@type": "ItemList", "itemListElement": ['
        '{"url": "https://www.listennotes.com/podcasts/a-abc123def4/"},'
        '{"url": "https://www.listennotes.com/podcasts/b-xyz987wvu6/"}]}'
        '</script>'
    )
    urls = _urls_from_listing(html)
    assert len(urls) == 2


def test_listennotes_fetch_listing_stage_advances_and_stops_short():
    src = ListenNotesPodcastsSource()
    src._session = object()
    src.throttle.wait = lambda: None

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        text = (
            '<script type="application/ld+json">{"@type": "ItemList", "itemListElement": []}</script>'
        )

    src._get = lambda url: FakeResp()
    src._process_urls = lambda urls: []
    rows, cursor = src.fetch({"stage": "listing", "listing_page": 1, "search_idx": 0, "search_page": 1})
    assert rows == []
    assert cursor["stage"] == "search"


def test_listennotes_registered():
    assert all_sources().get("listennotes_podcasts") is ListenNotesPodcastsSource


def test_wikidata_parse_film_binding():
    src = WikidataEntitiesSource()
    spec = QUERY_INDEX["films"]
    b = {
        "item": {"value": "http://www.wikidata.org/entity/Q83495"},
        "itemLabel": {"value": "The Matrix"},
        "itemDescription": {"value": "1999 film"},
        "year": {"value": "1999"},
        "countryLabel": {"value": "United States"},
        "imdb": {"value": "tt0133093"},
    }
    row = spec.parse_binding(b)
    assert row["wikidata_id"] == "Q83495"
    assert row["label_en"] == "The Matrix"
    assert row["year"] == 1999
    assert row["imdb_id"] == "tt0133093"
    assert row["entity_type"] == "film"


def test_wikidata_query_registry_has_expected_names():
    names = {q.name for q in QUERIES}
    for expected in ("films", "singers", "music_genres", "spotify_artists",
                     "video_game_series", "board_games"):
        assert expected in names
    assert len(QUERIES) == len(QUERY_INDEX)


def test_wikidata_fetch_short_page_ends_query_moves_to_next():
    src = WikidataEntitiesSource()
    src.queries = QUERIES[:2]
    src._sparql = lambda q: [{"item": {"value": "http://www.wikidata.org/entity/Q1"}}]
    rows, cursor = src.fetch({"qidx": 0, "offset": 0})
    assert len(rows) == 1
    assert cursor == {"qidx": 1, "offset": 0}


def test_wikidata_fetch_empty_page_ends_query():
    src = WikidataEntitiesSource()
    src.queries = QUERIES[:1]
    src._sparql = lambda q: []
    rows, cursor = src.fetch({"qidx": 0, "offset": 0})
    assert rows == []
    assert cursor is None


def test_wikidata_configure_restricts_to_single_query():
    import argparse

    src = WikidataEntitiesSource()
    src.configure(argparse.Namespace(query="films", list_queries=False))
    assert len(src.queries) == 1
    assert src.queries[0].name == "films"


def test_wikidata_registered():
    assert all_sources().get("wikidata_entities") is WikidataEntitiesSource


def test_pubchem_map_row_schema():
    src = PubChemCompoundsSource()
    row = src.map_row(2244, {
        "IUPACName": "aspirin", "MolecularFormula": "C9H8O4", "MolecularWeight": "180.16",
        "CanonicalSMILES": "CC(=O)OC1=CC=CC=C1C(=O)O", "InChI": "InChI=1S/...",
        "InChIKey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N", "Charge": 0, "XLogP": 1.2, "ExactMass": "180.042",
    }, ["Aspirin", "Acetylsalicylic acid"])
    assert row["cid"] == 2244
    assert row["iupac_name"] == "aspirin"
    assert row["synonyms"] == ["Aspirin", "Acetylsalicylic acid"]
    assert set(row) == {
        "cid", "iupac_name", "molecular_formula", "molecular_weight", "canonical_smiles",
        "inchi", "inchikey", "charge", "xlogp", "exact_mass", "synonyms",
    }


def test_pubchem_fetch_stops_when_search_empty():
    src = PubChemCompoundsSource()
    src._total_cids_cache = 100
    src._search_cids = lambda retstart, retmax=10000: []
    rows, cursor = src.fetch(0)
    assert rows == []
    assert cursor is None


def test_pubchem_fetch_advances_retstart_and_stops_at_total():
    src = PubChemCompoundsSource()
    src._total_cids_cache = 1
    src._search_cids = lambda retstart, retmax=10000: [2244]
    src._fetch_properties = lambda cids: {}
    src._fetch_synonyms = lambda cids: {}
    rows, cursor = src.fetch(0)
    assert len(rows) == 1
    assert cursor is None


def test_pubchem_registered():
    assert all_sources().get("pubchem_compounds") is PubChemCompoundsSource


def test_who_inn_map_row_schema():
    src = WhoInnSource()
    sub = {
        "_approvalIDDisplay": "R16CO5Y76E",
        "_name": "ASPIRIN",
        "names": [{"name": "Aspirin", "type": "INN", "languages": ["en"]}],
        "codes": [{"code": "50-78-2", "codeSystem": "CAS"}],
        "substanceClass": "chemical",
        "status": "approved",
    }
    row = src.map_row(sub)
    assert row["unii"] == "R16CO5Y76E"
    assert row["names"] == [{"name": "Aspirin", "name_type": "INN", "language": "en"}]
    assert set(row) == {
        "unii", "preferred_name", "names", "codes", "substance_class", "status",
    }


def test_who_inn_fetch_advances_type_when_short_of_total():
    src = WhoInnSource()
    src._get_page = lambda skip, name_type: {"content": [{"_approvalIDDisplay": "X1"}], "total": 1}
    rows, cursor = src.fetch({"type_idx": 0, "skip": 0})
    assert len(rows) == 1
    assert cursor == {"type_idx": 1, "skip": 0}


def test_who_inn_fetch_finishes_after_last_type():
    src = WhoInnSource()
    src._get_page = lambda skip, name_type: {}
    rows, cursor = src.fetch({"type_idx": len(NAME_TYPES) - 1, "skip": 0})
    assert rows == []
    assert cursor is None


def test_who_inn_registered():
    assert all_sources().get("who_inn") is WhoInnSource


def test_chembl_drugs_map_row_schema():
    src = ChemblDrugsSource()
    mol = {
        "molecule_chembl_id": "CHEMBL25",
        "pref_name": "ASPIRIN",
        "max_phase": 4,
        "molecule_type": "Small molecule",
        "molecule_synonyms": [{"synonyms": "Aspirin", "syn_type": "INN"}],
        "cross_references": [{"xref_src": "PubChem", "xref_id": "2244"}],
        "molecule_structures": {"standard_inchi": "InChI=1S/...", "canonical_smiles": "CC(=O)O"},
    }
    row = src.map_row(mol)
    assert row["chembl_id"] == "CHEMBL25"
    assert row["synonyms"] == [{"name": "Aspirin", "syn_type": "INN", "language": "en"}]
    assert row["pubchem_cid"] == 2244
    assert set(row) == {
        "chembl_id", "pref_name", "max_phase", "molecule_type", "first_approval",
        "atc_classifications", "usan_stem", "usan_stem_definition", "oral", "parenteral",
        "topical", "withdrawn_flag", "black_box_warning", "synonyms", "pubchem_cid",
        "inchi", "canonical_smiles",
    }


def test_chembl_drugs_fetch_stops_at_total_count():
    src = ChemblDrugsSource()
    src._get_page = lambda offset: {
        "molecules": [{"molecule_chembl_id": "CHEMBL1"}],
        "page_meta": {"total_count": 1},
    }
    rows, cursor = src.fetch(0)
    assert len(rows) == 1
    assert cursor is None


def test_chembl_drugs_registered():
    assert all_sources().get("chembl_drugs") is ChemblDrugsSource


def test_dailymed_names_stage_names_maps_rows():
    src = DailyMedNamesSource()
    src._get_names_page = lambda page: {
        "data": [{"name_type": "B", "drug_name": "Tylenol"}],
        "metadata": {"total_pages": 1},
    }
    rows, cursor = src.fetch({"stage": "names", "page": 1})
    assert rows == [{"name_type": "B", "drug_name": "Tylenol", "source": "drugnames"}]
    assert cursor == {"stage": "spls", "page": 1}


def test_dailymed_names_stage_spls_maps_rows_and_finishes():
    src = DailyMedNamesSource()
    src._get_spls_page = lambda page: {
        "data": [{"title": "Tylenol 500mg", "setid": "abc", "published_date": "2020-01-01"}],
        "metadata": {"total_pages": 1},
    }
    rows, cursor = src.fetch({"stage": "spls", "page": 1})
    assert rows[0]["name_type"] == "SPL"
    assert rows[0]["setid"] == "abc"
    assert cursor is None


def test_dailymed_names_registered():
    assert all_sources().get("dailymed_names") is DailyMedNamesSource


def test_wiktionary_extract_ipa_from_template():
    ipa = _extract_ipa("Some text {{IPA|en|/əˈspɪɹɪn/}} more text")
    assert ipa == ["əˈspɪɹɪn"]


def test_wiktionary_fetch_cat_stage_builds_queue_when_done():
    src = WiktionaryPronunciationsSource()
    src._list_category_members = lambda cont: (["Aspirin"], None)
    rows, cursor = src.fetch({"stage": "cat", "cat_cont": None, "en_titles": []})
    assert rows == []
    assert cursor["stage"] == "process"
    assert ["Aspirin", "en"] in cursor["queue"]
    assert ["Aspirin", "es"] in cursor["queue"]
    assert len(cursor["queue"]) == 12  # en + 11 other editions


def test_wiktionary_fetch_cat_stage_continues_pagination():
    src = WiktionaryPronunciationsSource()
    src._list_category_members = lambda cont: (["Aspirin"], "cont-token")
    rows, cursor = src.fetch({"stage": "cat", "cat_cont": None, "en_titles": []})
    assert rows == []
    assert cursor == {"stage": "cat", "cat_cont": "cont-token", "en_titles": ["Aspirin"]}


def test_wiktionary_fetch_process_stage_pops_batch():
    src = WiktionaryPronunciationsSource()
    src._fetch_pronunciations = lambda title, lang: (
        {"term": title, "language": lang, "ipa": ["x"], "wikitext_excerpt": "",
         "wiktionary_url": "u", "source_wiktionary": lang}
        if lang == "en" else None
    )
    queue = [["Aspirin", "en"], ["Aspirin", "es"]]
    rows, cursor = src.fetch({"stage": "process", "queue": queue})
    assert len(rows) == 1
    assert rows[0]["language"] == "en"
    assert cursor is None


def test_wiktionary_registered():
    assert all_sources().get("wiktionary_pronunciations") is WiktionaryPronunciationsSource


def test_batch3_scrapers_are_registered():
    reg = all_sources()
    assert reg.get("anilist_crawl") is AniListCrawlSource
    assert reg.get("listennotes_podcasts") is ListenNotesPodcastsSource
    assert reg.get("wikidata_entities") is WikidataEntitiesSource
    assert reg.get("pubchem_compounds") is PubChemCompoundsSource
    assert reg.get("who_inn") is WhoInnSource
    assert reg.get("chembl_drugs") is ChemblDrugsSource
    assert reg.get("dailymed_names") is DailyMedNamesSource
    assert reg.get("wiktionary_pronunciations") is WiktionaryPronunciationsSource
