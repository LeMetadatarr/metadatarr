"""Row-schema equivalence tests for the deezer/lastfm/erowid/health_canada/
cmu/rxnorm/anmat batch migrated onto the engine.

These lock the exact flat-row shape each scraper emits against a realistic
upstream sample, mirroring test_scrapers_migrated.py / test_scrapers_batch1.py
/ test_scrapers_batch2.py / test_scrapers_batch3.py.
"""
from __future__ import annotations

from metadatarr.scrapers.engine import all_sources
from metadatarr.scrapers.deezer_artists import DeezerArtistsSource
from metadatarr.scrapers.lastfm_artists import LastfmArtistsSource, TAGS
from metadatarr.scrapers.erowid_experiences import (
    ErowidExperiencesSource,
    ErowidSubstancesSource,
)
from metadatarr.scrapers.health_canada_drugs import HealthCanadaDrugsSource
from metadatarr.scrapers.cmu_pronunciations import CmuPronunciationsSource
from metadatarr.scrapers.rxnorm import RxNormSource, TARGET_TTYS
from metadatarr.scrapers.anmat_drugs import AnmatDrugsSource


# ---------------------------------------------------------------------------
# deezer_artists
# ---------------------------------------------------------------------------

def test_deezer_artists_map_row_schema():
    src = DeezerArtistsSource()
    row = src.map_row(27, {
        "name": "Daft Punk", "picture_big": "http://big.jpg", "picture": "http://small.jpg",
        "nb_album": 10, "nb_fan": 5_000_000, "link": "http://deezer.com/artist/27",
    })
    assert row == {
        "deezer_id": 27,
        "name": "Daft Punk",
        "picture_url": "http://big.jpg",
        "nb_album": 10,
        "nb_fan": 5_000_000,
        "url": "http://deezer.com/artist/27",
    }
    assert set(row) == {"deezer_id", "name", "picture_url", "nb_album", "nb_fan", "url"}


def test_deezer_artists_fetch_walks_id_chunk_and_stops_at_end():
    src = DeezerArtistsSource()
    src.end = 5
    src.throttle.wait = lambda: None
    src._fetch_artist = lambda i: ({"deezer_id": i, "name": f"a{i}"} if i in (1, 3) else None)
    rows, cursor = src.fetch(1)
    assert [r["deezer_id"] for r in rows] == [1, 3]
    assert cursor is None


def test_deezer_artists_fetch_stops_when_start_beyond_end():
    src = DeezerArtistsSource()
    src.end = 5
    rows, cursor = src.fetch(6)
    assert rows == []
    assert cursor is None


def test_deezer_artists_registered():
    assert all_sources().get("deezer_artists") is DeezerArtistsSource


# ---------------------------------------------------------------------------
# lastfm_artists
# ---------------------------------------------------------------------------

def test_lastfm_artists_parse_artist_info_schema():
    src = LastfmArtistsSource()
    info = {
        "artist": {
            "mbid": "abc-123", "name": "Daft Punk", "url": "http://lastfm/daftpunk",
            "stats": {"listeners": "1000000", "playcount": "5000000"},
            "tags": {"tag": [{"name": "electronic"}, {"name": "house"}]},
            "bio": {"summary": "French duo. <a href=\"...\">Read more</a>"},
            "similar": {"artist": [{"name": "Justice"}]},
        }
    }
    row = src._parse_artist_info(info)
    assert row["mbid"] == "abc-123"
    assert row["listeners"] == 1000000
    assert row["tags"] == ["electronic", "house"]
    assert row["similar_artists"] == ["Justice"]
    assert row["bio_summary"] == "French duo."
    assert row["entity_type"] == "musician"
    assert set(row) == {
        "mbid", "name", "url", "listeners", "playcount", "tags",
        "similar_artists", "bio_summary", "entity_type",
    }


def test_lastfm_artists_fetch_dedups_by_name_and_advances_page():
    src = LastfmArtistsSource()
    src._api_key = "key"
    src.throttle.wait = lambda: None

    def fake_api(method, **params):
        if method == "tag.gettopartists":
            return {"topartists": {"artist": [{"name": "A"}], "@attr": {"totalPages": "1"}}}
        return {"artist": {"mbid": "m1", "name": "A", "stats": {}}}

    src._api = fake_api
    rows, cursor = src.fetch({"tag_idx": 0, "tag_page": 1})
    assert len(rows) == 1
    assert cursor == {"tag_idx": 1, "tag_page": 1}

    # already-seen name is skipped on a subsequent page
    rows2, _ = src.fetch({"tag_idx": 0, "tag_page": 1})
    assert rows2 == []


def test_lastfm_artists_fetch_no_api_key_returns_nothing():
    src = LastfmArtistsSource()
    src._api_key = ""
    rows, cursor = src.fetch({"tag_idx": 0, "tag_page": 1})
    assert rows == []
    assert cursor is None


def test_lastfm_artists_tags_registry_size():
    assert len(TAGS) > 150


def test_lastfm_artists_registered():
    assert all_sources().get("lastfm_artists") is LastfmArtistsSource


# ---------------------------------------------------------------------------
# erowid_experiences / erowid_substances
# ---------------------------------------------------------------------------

class _FakeDose:
    def __init__(self):
        self.time = "T+0:00"
        self.amount = "100mg"
        self.method = "oral"
        self.substance = "Aspirin"
        self.form = "pill"


class _FakeExperience:
    def __init__(self):
        self.exp_id = 42
        self.url = "https://erowid.org/experiences/exp.php?ID=42"
        self.name = "A Trip Report"
        self.author = "Anonymous"
        self.substance = "Aspirin"
        self.text = "It was fine."
        self.year = "2020"
        self.gender = "M"
        self.age = "30"
        self.date = "2020-01-01"
        self.dosage = [_FakeDose()]


def test_erowid_experiences_map_row_schema():
    src = ErowidExperiencesSource()
    row = src.map_row(_FakeExperience())
    assert row["exp_id"] == 42
    assert row["dosage"] == [{
        "time": "T+0:00", "amount": "100mg", "method": "oral",
        "substance": "Aspirin", "form": "pill",
    }]
    assert set(row) == {
        "exp_id", "url", "name", "author", "substance", "text", "year",
        "gender", "age", "date", "dosage",
    }


def test_erowid_experiences_fetch_skips_seen_and_stops_at_max_id():
    src = ErowidExperiencesSource()
    src._seen = {"2"}
    src.throttle.wait = lambda: None
    calls = []

    def fake_get_experience(exp_id, transport=None):
        calls.append(exp_id)
        return _FakeExperience() if exp_id != 3 else None

    import metadatarr.scrapers.erowid_experiences as mod
    mod.get_experience = fake_get_experience
    try:
        rows, cursor = src.fetch(1)
    finally:
        pass
    assert 2 not in calls  # already seen, skipped before hitting the network
    assert 3 in calls
    assert all(r["exp_id"] == 42 for r in rows)  # fake always returns exp_id 42
    assert cursor == 501  # 1 + EXP_CHUNK(500)


def test_erowid_experiences_fetch_done_past_max_id():
    src = ErowidExperiencesSource()
    from metadatarr.scrapers.erowid_experiences import MAX_EXPERIENCE_ID
    rows, cursor = src.fetch(MAX_EXPERIENCE_ID + 1)
    assert rows == []
    assert cursor is None


class _FakeListing:
    def __init__(self, name, url):
        self.name = name
        self.url = url


class _FakeSubstanceInfo:
    def __init__(self):
        self.name = "Aspirin"
        self.url = "https://erowid.org/pharms/aspirin/"
        self.picture = "pic.jpg"
        self.other_names = ["ASA"]
        self.description = "A pain reliever."
        self.info = "info text"
        self.chem_name = "acetylsalicylic acid"
        self.effects = ["pain relief"]
        self.uses = ["headache"]
        self.family = "salicylate"
        self.genus = None
        self.species = None


def test_erowid_substances_map_row_schema():
    src = ErowidSubstancesSource()
    row = src.map_row(_FakeSubstanceInfo())
    assert row["name"] == "Aspirin"
    assert row["other_names"] == ["ASA"]
    assert set(row) == {
        "name", "url", "picture", "other_names", "description", "info",
        "chem_name", "effects", "uses", "family", "genus", "species",
    }


def test_erowid_substances_fetch_walks_categories_and_dedups():
    src = ErowidSubstancesSource()
    src._seen = {"Aspirin"}
    src.throttle.wait = lambda: None

    import metadatarr.scrapers.erowid_experiences as mod
    cats = sorted(mod._CATEGORY_BASES)
    mod._extract_list = lambda category, transport=None: [
        _FakeListing("Aspirin", "u1"), _FakeListing("Ibuprofen", "u2"),
    ]
    mod.parse_substance_page = lambda url, transport=None: _FakeSubstanceInfo()

    rows, cursor = src.fetch(0)
    assert len(rows) == 1  # Aspirin skipped as already seen
    assert cursor == (1 if len(cats) > 1 else None)


def test_erowid_scrapers_registered():
    reg = all_sources()
    assert reg.get("erowid_experiences") is ErowidExperiencesSource
    assert reg.get("erowid_substances") is ErowidSubstancesSource


# ---------------------------------------------------------------------------
# health_canada_drugs
# ---------------------------------------------------------------------------

def test_health_canada_drugs_registered():
    assert all_sources().get("health_canada_drugs") is HealthCanadaDrugsSource


def test_health_canada_drugs_fetch_returns_none_for_none_cursor():
    src = HealthCanadaDrugsSource()
    rows, cursor = src.fetch(None)
    assert rows == []
    assert cursor is None


def test_health_canada_drugs_parses_tsv_columns(tmp_path):
    import zipfile
    from metadatarr.scrapers.health_canada_drugs import _DRUG_COLS, _ING_COLS, _STATUS_COLS

    zip_path = tmp_path / "allfiles.zip"
    drug_row = ",".join(f'"{c}{i}"' for i, c in enumerate(_DRUG_COLS))
    ing_row = ",".join(f'"{c}{i}"' for i, c in enumerate(_ING_COLS))
    # drug_code=drug_code0 for both; strength fields index-matched
    status_row = '"drug_code0","1","APPROVED","2020-01-01","L1"'
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("drug.txt", drug_row + "\n")
        zf.writestr("ingred.txt", ing_row + "\n")
        zf.writestr("status.txt", status_row + "\n")

    src = HealthCanadaDrugsSource()
    src._output_dir = tmp_path
    import metadatarr.scrapers.health_canada_drugs as mod
    mod._download_zip = lambda output_dir: zip_path

    rows, cursor = src.fetch(0)
    assert cursor is None
    assert len(rows) == 1
    row = rows[0]
    assert row["drug_code"] == "drug_code0"
    assert row["status"] == "APPROVED"
    assert len(row["active_ingredients"]) == 1
    assert set(row) == {
        "drug_code", "drug_identification_number", "brand_name", "descriptor",
        "class_name", "company_name", "number_of_ais", "last_update_date",
        "status", "active_ingredients",
    }


# ---------------------------------------------------------------------------
# cmu_pronunciations
# ---------------------------------------------------------------------------

def test_cmu_pronunciations_map_row_schema():
    src = CmuPronunciationsSource()
    row = src.map_row("aspirin", "AE1 S P ER0 IH0 N", 1, "cmudict.dict")
    assert row == {
        "term": "aspirin", "arpabet": "AE1 S P ER0 IH0 N",
        "variant_num": 1, "source_file": "cmudict.dict",
    }
    assert set(row) == {"term", "arpabet", "variant_num", "source_file"}


def test_cmu_pronunciations_fetch_matches_and_compounds(tmp_path):
    (tmp_path / "cmudict.dict").write_text(
        "aspirin AE1 S P ER0 IH0 N\n"
        "amoxicillin AH0 M AA2 K S AH0 S IH1 L IH0 N\n"
        "clavulanate K L AE1 V Y AH0 L AH0 N EY2 T\n",
        encoding="utf-8",
    )
    (tmp_path / "other_drugs.jsonl").write_text(
        '{"generic_name": "Aspirin"}\n'
        '{"generic_name": "amoxicillin clavulanate"}\n'
        '{"generic_name": "unknownium"}\n',
        encoding="utf-8",
    )

    src = CmuPronunciationsSource()
    src._output_dir = tmp_path
    rows, cursor = src.fetch(0)
    assert cursor is None
    terms = {r["term"]: r for r in rows}
    assert terms["aspirin"]["variant_num"] == 1
    assert terms["amoxicillin clavulanate"]["source_file"] == "cmudict.dict+compound"
    assert "unknownium" not in terms


def test_cmu_pronunciations_fetch_none_cursor_is_noop():
    src = CmuPronunciationsSource()
    rows, cursor = src.fetch(None)
    assert rows == []
    assert cursor is None


def test_cmu_pronunciations_registered():
    assert all_sources().get("cmu_pronunciations") is CmuPronunciationsSource


# ---------------------------------------------------------------------------
# rxnorm
# ---------------------------------------------------------------------------

def test_rxnorm_map_row_schema():
    src = RxNormSource()
    row = src.map_row({"rxcui": "1191", "name": "Aspirin", "tty": "IN"}, ["N02BA01"])
    assert row == {"rxcui": "1191", "name": "Aspirin", "tty": "IN", "atc_codes": ["N02BA01"]}
    assert set(row) == {"rxcui", "name", "tty", "atc_codes"}


def test_rxnorm_fetch_dedups_and_only_fetches_atc_for_ingredients():
    src = RxNormSource()
    src._concepts = [
        {"rxcui": "1", "name": "Aspirin", "tty": "IN"},
        {"rxcui": "2", "name": "Tylenol", "tty": "BN"},
    ]
    src._seen = {"2"}
    atc_calls = []
    src._get_atc = lambda rxcui: atc_calls.append(rxcui) or ["X"]

    rows, cursor = src.fetch(0)
    assert cursor is None
    assert [r["rxcui"] for r in rows] == ["1"]  # rxcui 2 skipped (already seen)
    assert atc_calls == ["1"]  # only the IN-type concept triggers an ATC lookup


def test_rxnorm_all_concepts_dedups_by_rxcui_across_ttys():
    src = RxNormSource()
    calls = {"n": 0}

    def fake_get(path, **params):
        calls["n"] += 1
        tty = params.get("tty")
        return {"minConceptGroup": {"minConcept": [{"rxcui": "1", "name": "A", "tty": tty}]}}

    src._get = fake_get
    concepts = src._all_concepts()
    assert calls["n"] == len(TARGET_TTYS)
    assert len(concepts) == 1  # deduped by rxcui even though every TTY returned rxcui "1"


def test_rxnorm_registered():
    assert all_sources().get("rxnorm_drugs") is RxNormSource


# ---------------------------------------------------------------------------
# anmat_drugs
# ---------------------------------------------------------------------------

def test_anmat_drugs_map_row_schema():
    src = AnmatDrugsSource()
    row = src.map_row({
        "nombre_comercial": "Aspirineta", "nombre_generico": "Acido acetilsalicilico",
        "laboratorio_titular": "Bayer", "concentracion": "100mg",
        "forma_farmaceutica": "comprimido", "presentacion": "caja x 30",
        "numero_certificado": "12345",
    }, "http://example.com/data.csv")
    assert row == {
        "nombre_comercial": "Aspirineta",
        "nombre_generico": "Acido acetilsalicilico",
        "laboratorio_titular": "Bayer",
        "concentracion": "100mg",
        "forma_farmaceutica": "comprimido",
        "presentacion": "caja x 30",
        "numero_certificado": "12345",
        "language": "es-AR",
        "source_url": "http://example.com/data.csv",
    }
    assert set(row) == {
        "nombre_comercial", "nombre_generico", "laboratorio_titular", "concentracion",
        "forma_farmaceutica", "presentacion", "numero_certificado", "language", "source_url",
    }


def test_anmat_drugs_fetch_none_cursor_is_noop():
    src = AnmatDrugsSource()
    rows, cursor = src.fetch(None)
    assert rows == []
    assert cursor is None


def test_anmat_drugs_registered():
    assert all_sources().get("anmat_drugs") is AnmatDrugsSource


# ---------------------------------------------------------------------------
# batch4 registration roundup
# ---------------------------------------------------------------------------

def test_batch4_scrapers_are_registered():
    reg = all_sources()
    assert reg.get("deezer_artists") is DeezerArtistsSource
    assert reg.get("lastfm_artists") is LastfmArtistsSource
    assert reg.get("erowid_experiences") is ErowidExperiencesSource
    assert reg.get("erowid_substances") is ErowidSubstancesSource
    assert reg.get("health_canada_drugs") is HealthCanadaDrugsSource
    assert reg.get("cmu_pronunciations") is CmuPronunciationsSource
    assert reg.get("rxnorm_drugs") is RxNormSource
    assert reg.get("anmat_drugs") is AnmatDrugsSource
