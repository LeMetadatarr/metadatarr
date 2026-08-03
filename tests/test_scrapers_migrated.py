"""Row-schema equivalence tests for scrapers migrated onto the engine.

These lock the exact flat-row shape each scraper emits (the contract the
LeData datasets depend on) against a realistic upstream sample, so a future
engine change can't silently alter the output schema.
"""
from __future__ import annotations

from metadatarr.scrapers.openfda_labels import OpenFDALabels
from metadatarr.scrapers.openlibrary_books import OpenLibraryBooks


def test_openlibrary_map_row_schema():
    src = OpenLibraryBooks()
    doc = {
        "key": "/works/OL45804W",
        "title": "Fantastic Mr Fox",
        "subtitle": "a story",
        "author_name": ["Roald Dahl"],
        "author_key": ["OL34184A"],
        "first_publish_year": 1970,
        "subject": [f"s{i}" for i in range(40)],
        "isbn": [f"isbn{i}" for i in range(9)],
        "publisher": [f"p{i}" for i in range(9)],
        "language": [f"l{i}" for i in range(20)],
        "number_of_pages_median": 96,
        "ebook_access": "borrowable",
        "has_fulltext": True,
        "edition_count": 120,
        "cover_i": 8739161,
    }
    row = src.map_row(doc)
    assert row["olid"] == "OL45804W"
    assert row["title"] == "Fantastic Mr Fox"
    assert row["authors"] == ["Roald Dahl"]
    # truncation contracts preserved from the original scraper
    assert len(row["subjects"]) == 30
    assert len(row["isbn_10"]) == 5
    assert row["isbn_13"] == []
    assert len(row["publisher"]) == 5
    assert len(row["language"]) == 10
    assert row["has_fulltext"] is True
    assert set(row) == {
        "olid", "title", "subtitle", "authors", "author_key",
        "first_publish_year", "subjects", "isbn_10", "isbn_13", "publisher",
        "language", "number_of_pages_median", "ebook_access", "has_fulltext",
        "edition_count", "cover_i",
    }


def test_openlibrary_map_row_drops_records_without_olid():
    assert OpenLibraryBooks().map_row({"key": "", "title": "x"}) is None


def test_openlibrary_partitions_stable_and_seeded():
    parts = OpenLibraryBooks().partitions()
    assert parts[0] == {"subject": "fiction"}
    assert len(parts) == 64
    assert all(set(p) == {"subject"} for p in parts)


def test_openfda_map_row_flattens_openfda_block():
    src = OpenFDALabels()
    rec = {
        "set_id": "abc-123",
        "id": "id-1",
        "effective_time": "20200101",
        "openfda": {
            "brand_name": ["Tylenol"],
            "generic_name": ["acetaminophen"],
            "manufacturer_name": ["J&J"],
            "product_type": ["HUMAN OTC DRUG"],
            "route": ["ORAL"],
            "substance_name": ["ACETAMINOPHEN"],
            "package_ndc": ["50580-449"],
            "rxcui": ["1234"],
            "spl_id": ["spl-1"],
        },
        "indications_and_usage": ["pain", "fever"],
        "warnings": ["do not exceed"],
    }
    row = src.map_row(rec)
    assert row["set_id"] == "abc-123"
    assert row["brand_name"] == "Tylenol"          # _first: list -> scalar
    assert row["generic_name"] == "acetaminophen"
    assert row["route"] == ["ORAL"]                # list fields stay lists
    assert row["ndc"] == ["50580-449"]             # package_ndc -> ndc
    assert row["indications_and_usage"] == "pain fever"  # _join
    assert row["boxed_warning"] == ""              # absent -> ""


def test_openfda_partitions_cover_years_plus_catchall():
    parts = OpenFDALabels().partitions()
    assert len(parts) == (2030 - 1950) + 1
    assert parts[0] == {"search": "effective_time:[19500101+TO+19501231]"}
    assert parts[-1] == {"search": "_missing_:effective_time"}


def test_both_scrapers_are_registered():
    from metadatarr.scrapers.engine import all_sources
    import metadatarr.scrapers.openfda_labels  # noqa: F401
    import metadatarr.scrapers.openlibrary_books  # noqa: F401

    reg = all_sources()
    assert reg.get("openlibrary_books") is OpenLibraryBooks
    assert reg.get("openfda_labels") is OpenFDALabels
