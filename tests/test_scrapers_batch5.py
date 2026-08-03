"""Row-schema equivalence tests for the pmda/codifa/fass/titck/swissmedic/
who_atc/grls HTML-scraping batch migrated onto the engine.

These lock the exact flat-row shape each scraper emits against a realistic
upstream sample, mirroring test_scrapers_migrated.py / test_scrapers_batch3.py.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from metadatarr.scrapers.engine import all_sources
from metadatarr.scrapers.pmda_drugs import PMDADrugsSource, _parse_page
from metadatarr.scrapers.codifa_drugs import (
    CodifaDrugsSource,
    _parse_letter_page,
    _parse_detail_page,
)
from metadatarr.scrapers.fass_drugs import FassDrugsSource, _parse_letter_page as fass_parse_letter_page
from metadatarr.scrapers.titck_drugs import TitckDrugsSource, _parse_workbook as titck_parse_workbook
from metadatarr.scrapers.swissmedic_drugs import (
    SwissmedicDrugsSource,
    _parse_workbook as swissmedic_parse_workbook,
    _find_xlsx_url,
    _parse_date,
)
from metadatarr.scrapers.who_atc import WhoAtcSource, _parse_child_links, _parse_substance_table
from metadatarr.scrapers.grls_drugs import GrlsDrugsSource, _parse_results


def test_pmda_parse_page_schema():
    html = """
    <table>
      <tr><th>Brand Name</th><th>Non-proprietary Name</th><th>Approved in</th></tr>
      <tr><td>Tylenol</td><td>Acetaminophen</td><td>2020-01</td></tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = _parse_page(soup)
    assert rows == [{
        "brand_name": "Tylenol",
        "nonproprietary_name": "Acetaminophen",
        "approved_in": "2020-01",
        "language": "en",
        "country": "JP",
    }]


def test_pmda_parse_page_skips_tables_without_expected_headers():
    html = "<table><tr><th>foo</th></tr><tr><td>bar</td></tr></table>"
    soup = BeautifulSoup(html, "html.parser")
    assert _parse_page(soup) == []


def test_codifa_parse_letter_page_extracts_slug_and_href():
    html = '<a href="/farmaci/a/aspirina-100mg">Aspirina 100mg</a>'
    rows = _parse_letter_page(html, "a")
    assert rows == [{"brand_name": "Aspirina 100mg", "slug": "aspirina-100mg",
                     "href": "/farmaci/a/aspirina-100mg"}]


def test_codifa_parse_detail_page_dl():
    html = (
        "<dl>"
        "<dt>Principio Attivo</dt><dd>acido acetilsalicilico</dd>"
        "<dt>Classe Terapeutica</dt><dd>antinfiammatori</dd>"
        "<dt>ATC</dt><dd>N02BA01</dd>"
        "<dt>Forma Farmaceutica</dt><dd>compresse</dd>"
        "</dl>"
    )
    detail = _parse_detail_page(html)
    assert detail == {
        "principio_attivo": "acido acetilsalicilico",
        "classe_terapeutica": "antinfiammatori",
        "atc": "N02BA01",
        "forma_farmaceutica": "compresse",
    }


def test_codifa_final_row_merges_listing_and_detail():
    listing = _parse_letter_page(
        '<a href="/farmaci/a/aspirina-100mg">Aspirina 100mg</a>', "a")[0]
    detail = _parse_detail_page("<dl><dt>ATC</dt><dd>N02BA01</dd></dl>")
    row = {
        "brand_name": listing["brand_name"],
        "slug": listing["slug"],
        "href": listing["href"],
        "letter": "a",
        "language": "it",
        "source": "codifa",
        **detail,
    }
    assert row == {
        "brand_name": "Aspirina 100mg",
        "slug": "aspirina-100mg",
        "href": "/farmaci/a/aspirina-100mg",
        "letter": "a",
        "language": "it",
        "source": "codifa",
        "atc": "N02BA01",
    }


def test_fass_parse_letter_page_extracts_npl_id_and_trade_name():
    html = """
    <h2>Alvedon</h2>
    <ul>
      <li><a href="/LIB/product/12345">Tablet 500mg</a></li>
    </ul>
    """
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    rows = fass_parse_letter_page(soup, seen)
    assert rows == [{
        "trade_name": "Alvedon",
        "dosage_form": "Tablet 500mg",
        "manufacturer": "",
        "npl_id": "12345",
        "product_url": "https://fass.se/LIB/product/12345",
        "language": "sv",
    }]


def test_fass_parse_letter_page_dedups_within_page():
    html = """
    <h2>Alvedon</h2>
    <ul>
      <li><a href="/LIB/product/12345">Tablet</a></li>
      <li><a href="/LIB/product/12345">Tablet</a></li>
    </ul>
    """
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    rows = fass_parse_letter_page(soup, seen)
    assert len(rows) == 1


def test_titck_parse_workbook_filters_non_aktif(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    for _ in range(3):
        ws.append([None] * 7)  # rows 1-3 are header/junk, data starts row 4
    ws.append(["Parol", "8699000000001", "N02BE01", "Paracetamol", "Firma A", "Normal", "Aktif"])
    ws.append(["Old Drug", "8699000000002", "N02BE02", "Old", "Firma B", "Normal", "Pasif"])

    rows = titck_parse_workbook(ws)
    assert rows == [{
        "ilac_adi": "Parol",
        "barkod": "8699000000001",
        "atc_kodu": "N02BE01",
        "atc_adi": "Paracetamol",
        "firma_adi": "Firma A",
        "recete_turu": "Normal",
        "durumu": "Aktif",
        "language": "tr",
    }]


def test_swissmedic_find_xlsx_url_extracts_link():
    html = '<a href="/dam/foo/zugelassene_arzneimittel_x.xlsx.download.xlsx/x.xlsx">list</a>'
    assert _find_xlsx_url(html) == (
        "https://www.swissmedic.ch/dam/foo/zugelassene_arzneimittel_x.xlsx.download.xlsx/x.xlsx"
    )


def test_swissmedic_find_xlsx_url_falls_back():
    from metadatarr.scrapers.swissmedic_drugs import FALLBACK_XLSX_URL
    assert _find_xlsx_url("<html>no links here</html>") == FALLBACK_XLSX_URL


def test_swissmedic_parse_date_handles_datetime_and_string():
    import datetime
    assert _parse_date(None) == ""
    assert _parse_date("2020-01-01") == "2020-01-01"
    assert _parse_date(datetime.date(2020, 1, 1)) == "2020-01-01"


def test_swissmedic_parse_workbook_schema(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    for _ in range(7):
        ws.append([None] * 8)  # rows 1-7 junk/header, data starts row 8 (DATA_START=7, 0-idx)
    ws.append(["12345", None, "Dafalgan", "Bristol-Myers", "N02BE01", None,
               "B", "2020-01-01"])

    rows = swissmedic_parse_workbook(ws)
    assert rows == [{
        "zulassungsnummer": "12345",
        "bezeichnung": "Dafalgan",
        "zulassungsinhaber": "Bristol-Myers",
        "heilmittelcode": "N02BE01",
        "abgabekategorie": "B",
        "erstzulassung": "2020-01-01",
        "language": "de-CH",
    }]


def test_who_atc_parse_child_links_filters_by_code_length():
    html = (
        '<a href="?code=A01">A01 - group</a>'
        '<a href="?code=A02">A02 - other</a>'
        '<a href="?code=A">A - parent</a>'
        '<a href="?code=A01AA">too deep</a>'
        '<a href="?code=A03">Guidelines</a>'
    )
    links = _parse_child_links(html, "A")
    assert links == [("A01", "A01 - group"), ("A02", "A02 - other")]


def test_who_atc_parse_substance_table_schema():
    html = """
    <table>
      <tr><td>ATC code</td><td>Name</td><td>DDD</td><td>U</td><td>Adm.R</td><td>Note</td></tr>
      <tr><td>A01AA01</td><td>sodium fluoride</td><td>1</td><td>mg</td><td>O</td><td></td></tr>
    </table>
    """
    hierarchy = {
        "level1_code": "A", "level1_name": "ALIMENTARY",
        "level2_code": "A01", "level2_name": "STOMATOLOGICAL",
        "level3_code": "A01A", "level3_name": "STOMATOLOGICAL PREP",
        "level4_code": "A01AA", "level4_name": "Caries prophylactic agents",
    }
    rows = _parse_substance_table(html, hierarchy)
    assert rows == [{
        "atc_code": "A01AA01",
        "name": "sodium fluoride",
        "ddd": "1",
        "uom": "mg",
        "adm_r": "O",
        "note": "",
        **hierarchy,
    }]


def test_grls_parse_results_schema():
    html = """
    <table>
      <tr><th>Регистрационный номер</th><th>Торговое наименование</th>
          <th>МНН</th><th>Производитель</th></tr>
      <tr><td>ЛП-000001</td><td>Аспирин</td><td>ацетилсалициловая кислота</td><td>Bayer</td></tr>
    </table>
    """
    rows = _parse_results(html)
    assert rows == [{
        "language": "ru",
        "source": "grls",
        "reg_number": "ЛП-000001",
        "trade_name": "Аспирин",
        "inn_mnn": "ацетилсалициловая кислота",
        "manufacturer": "Bayer",
    }]


def test_all_seven_scrapers_are_registered():
    reg = all_sources()
    assert reg.get("pmda_drugs") is PMDADrugsSource
    assert reg.get("codifa_drugs") is CodifaDrugsSource
    assert reg.get("fass_drugs") is FassDrugsSource
    assert reg.get("titck_drugs") is TitckDrugsSource
    assert reg.get("swissmedic_drugs") is SwissmedicDrugsSource
    assert reg.get("who_atc") is WhoAtcSource
    assert reg.get("grls_drugs") is GrlsDrugsSource
