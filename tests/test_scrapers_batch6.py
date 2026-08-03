"""Row-schema equivalence tests for the aemps/ansm/anvisa/cbg/isp/pharmac/
fda_ndc/fda_orange_book/ema_epar/kegg/drugbank drug-registry batch migrated
onto the engine.

These lock the exact flat-row shape each scraper emits against a realistic
upstream sample, mirroring test_scrapers_migrated.py / test_scrapers_batch4.py
/ test_scrapers_batch5.py.
"""
from __future__ import annotations

from metadatarr.scrapers.engine import all_sources
from metadatarr.scrapers.aemps_drugs import AempsDrugsSource
from metadatarr.scrapers.ansm_drugs import AnsmDrugsSource
from metadatarr.scrapers.anvisa_drugs import AnvisaDrugsSource
from metadatarr.scrapers.cbg_drugs import CbgDrugsSource
from metadatarr.scrapers.isp_drugs import IspDrugsSource
from metadatarr.scrapers.pharmac_drugs import PharmacDrugsSource, _parse_workbook as pharmac_parse_workbook
from metadatarr.scrapers.fda_ndc import FdaNdcSource, _row as fda_ndc_row
from metadatarr.scrapers.fda_orange_book import FdaOrangeBookSource, _parse_products
from metadatarr.scrapers.ema_epar import EmaEparSource, _parse_xlsx, _map_column, _is_header_row
from metadatarr.scrapers.kegg_drugs import (
    KeggDrugsSource,
    _parse_names,
    _parse_kegg_record,
    _split_records,
)
from metadatarr.scrapers.drugbank_open import DrugbankOpenSource, _parse_row as drugbank_parse_row


# ---------------------------------------------------------------------------
# aemps_drugs
# ---------------------------------------------------------------------------

def test_aemps_drugs_map_row_schema():
    src = AempsDrugsSource()
    row = src.map_row({
        "nregistro": "12345", "nombre": "Aspirina 100mg",
        "labtitular": "Bayer", "labcomercializador": "Bayer ES",
        "viasAdministracion": [{"nombre": "Oral"}],
        "formaFarmaceutica": {"nombre": "comprimido"},
        "vtm": {"nombre": "aspirin"},
        "dosis": "100mg", "comercializado": True, "receta": False,
        "generico": False, "huerfano": False,
    })
    assert row == {
        "nregistro": "12345",
        "nombre": "Aspirina 100mg",
        "laboratorio_titular": "Bayer",
        "laboratorio_comercializador": "Bayer ES",
        "vias_administracion": ["Oral"],
        "forma_farmaceutica": "comprimido",
        "vtm": "aspirin",
        "dosis": "100mg",
        "comercializado": True,
        "receta": False,
        "generico": False,
        "huerfano": False,
        "language": "es",
        "source": "aemps_cima",
    }


def test_aemps_drugs_fetch_stops_after_total_pages(monkeypatch):
    src = AempsDrugsSource()
    src.throttle.wait = lambda: None

    def fake_get_json(url, params=None):
        return {
            "totalFilas": 3, "tamanioPagina": 2,
            "resultados": [{"nregistro": "1"}, {"nregistro": "2"}]
                          if params["pagina"] == 1 else [{"nregistro": "3"}],
        }

    src.get_json = fake_get_json
    rows, cursor = src.fetch(1)
    assert len(rows) == 2
    assert cursor == 2
    rows2, cursor2 = src.fetch(2)
    assert len(rows2) == 1
    assert cursor2 is None


def test_aemps_drugs_registered():
    assert all_sources().get("aemps_drugs") is AempsDrugsSource


# ---------------------------------------------------------------------------
# ansm_drugs
# ---------------------------------------------------------------------------

class _FakeAnsmSession:
    def __init__(self, compo_text, spec_text):
        self._urls = {}
        self.compo_text = compo_text
        self.spec_text = spec_text
        self.headers = {}

    def get(self, url, timeout=None, verify=None):
        class _R:
            def __init__(self, content):
                self.content = content

            def raise_for_status(self):
                pass

        if "COMPO" in url:
            return _R(self.compo_text.encode("utf-8"))
        return _R(self.spec_text.encode("utf-8"))


def test_ansm_drugs_fetch_joins_composition_and_speciality(monkeypatch):
    compo = "62012345\tcp\tSUB1\tAcide acetylsalicylique\t500mg\n"
    spec = "62012345\tASPIRINE 500 mg\tcomprime\torale\t1\t\tcommercialisee\t\t\t\ttitulaire A\n"

    import metadatarr.scrapers.ansm_drugs as mod
    monkeypatch.setattr(mod.requests, "Session", lambda: _FakeAnsmSession(compo, spec))

    src = AnsmDrugsSource()
    rows, cursor = src.fetch(0)
    assert cursor is None
    assert len(rows) == 1
    row = rows[0]
    assert row["cis_code"] == "62012345"
    assert row["specialite_name"] == "ASPIRINE 500 mg"
    assert row["substances"] == [{"code": "SUB1", "name": "Acide acetylsalicylique", "dosage": "500mg"}]
    assert set(row) == {
        "cis_code", "specialite_name", "dosage_form", "route", "status",
        "commercialisation_status", "holders", "substances", "language", "source",
    }


def test_ansm_drugs_fetch_none_cursor_is_noop():
    src = AnsmDrugsSource()
    rows, cursor = src.fetch(None)
    assert rows == []
    assert cursor is None


def test_ansm_drugs_registered():
    assert all_sources().get("ansm_drugs") is AnsmDrugsSource


# ---------------------------------------------------------------------------
# anvisa_drugs
# ---------------------------------------------------------------------------

def test_anvisa_drugs_fetch_parses_csv(monkeypatch):
    import metadatarr.scrapers.anvisa_drugs as mod

    csv_text = (
        "TIPO_PRODUTO;NOME_PRODUTO;DATA_FINALIZACAO_PROCESSO;CATEGORIA_REGULATORIA;"
        "NUMERO_REGISTRO_PRODUTO;DATA_VENCIMENTO_REGISTRO;NUMERO_PROCESSO;"
        "CLASSE_TERAPEUTICA;EMPRESA_DETENTORA_REGISTRO;SITUACAO_REGISTRO;PRINCIPIO_ATIVO\n"
        '"Generico";"ASPIRINA";"2020-01-01";"Novo";"12345";"2030-01-01";"999";'
        '"Antitermico";"Bayer";"Ativo";"ACIDO ACETILSALICILICO"\n'
    )

    class _FakeResp:
        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield csv_text.encode("utf-8")

    class _FakeSession:
        headers = {}

        def get(self, url, timeout=None, verify=None, stream=None):
            return _FakeResp()

    monkeypatch.setattr(mod.requests, "Session", lambda: _FakeSession())

    src = AnvisaDrugsSource()
    rows, cursor = src.fetch(0)
    assert cursor is None
    assert len(rows) == 1
    row = rows[0]
    assert row["nome_produto"] == "ASPIRINA"
    assert row["principio_ativo"] == "ACIDO ACETILSALICILICO"
    assert set(row) == {
        "tipo_produto", "nome_produto", "data_finalizacao", "categoria_regulatoria",
        "numero_registro", "data_vencimento", "numero_processo", "classe_terapeutica",
        "empresa_detentora", "situacao", "principio_ativo",
    }


def test_anvisa_drugs_fetch_none_cursor_is_noop():
    src = AnvisaDrugsSource()
    rows, cursor = src.fetch(None)
    assert rows == []
    assert cursor is None


def test_anvisa_drugs_registered():
    assert all_sources().get("anvisa_drugs") is AnvisaDrugsSource


# ---------------------------------------------------------------------------
# cbg_drugs
# ---------------------------------------------------------------------------

def test_cbg_drugs_fetch_skips_empty_productnaam(monkeypatch):
    import metadatarr.scrapers.cbg_drugs as mod

    csv_text = (
        "REGISTRATIENUMMER|PRODUCTNAAM|INSCHRIJVINGSDATUM|HANDELSVERGUNNINGHOUDER|"
        "AFLEVERSTATUS|FARMACEUTISCHEVORM|ATC|WERKZAMESTOFFEN\n"
        "RVG 12345|Aspirine 100mg|2000-01-01|Bayer BV|UA|tablet|N02BA01|acetylsalicylzuur\n"
        "RVG 99999||2000-01-01|Bayer BV|UA|tablet|N02BA01|acetylsalicylzuur\n"
    )

    class _FakeResp:
        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield csv_text.encode("utf-8")

    class _FakeSession:
        headers = {}

        def get(self, url, timeout=None, verify=None, stream=None):
            return _FakeResp()

    monkeypatch.setattr(mod.requests, "Session", lambda: _FakeSession())

    src = CbgDrugsSource()
    rows, cursor = src.fetch(0)
    assert cursor is None
    assert len(rows) == 1
    row = rows[0]
    assert row["productnaam"] == "Aspirine 100mg"
    assert row["language"] == "nl"
    assert set(row) == {
        "registratienummer", "productnaam", "inschrijvingsdatum",
        "handelsvergunninghouder", "afleverstatus", "farmaceutischevorm",
        "atc", "werkzamestoffen", "language",
    }


def test_cbg_drugs_registered():
    assert all_sources().get("cbg_drugs") is CbgDrugsSource


# ---------------------------------------------------------------------------
# isp_drugs
# ---------------------------------------------------------------------------

def test_isp_drugs_fetch_parses_csv(monkeypatch):
    import metadatarr.scrapers.isp_drugs as mod

    csv_text = (
        "N° Registro;Nombre Producto;Razon Social Titular;Condicion Venta\n"
        "F-12345/20;Aspirina 500mg;Bayer Chile;Directa\n"
    )

    class _FakeResp:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            pass

    class _FakeSession:
        headers = {}

        def get(self, url, timeout=None, verify=None):
            return _FakeResp(csv_text.encode("utf-8"))

    monkeypatch.setattr(mod.requests, "Session", lambda: _FakeSession())

    src = IspDrugsSource()
    rows, cursor = src.fetch(0)
    assert cursor is None
    assert len(rows) == 1
    row = rows[0]
    assert row["numero_registro"] == "F-12345/20"
    assert row["language"] == "es-CL"
    assert set(row) == {"numero_registro", "nombre_producto", "titular", "condicion_venta", "language"}


def test_isp_drugs_registered():
    assert all_sources().get("isp_drugs") is IspDrugsSource


# ---------------------------------------------------------------------------
# pharmac_drugs
# ---------------------------------------------------------------------------

def test_pharmac_parse_workbook_dedups_by_composite_key():
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    for _ in range(3):
        ws.append([None] * 10)  # rows 1-3 junk/header, data starts row 4 (DATA_START=3, 0-idx)
    ws.append(["Paracetamol", "500mg tab", "Panadol", "1234", "NZ001", 1.5, "$0.00", "", "tab", "Y"])
    ws.append(["Paracetamol", "500mg tab", "Panadol", "1234", "NZ001", 1.5, "$0.00", "", "tab", "Y"])

    rows = pharmac_parse_workbook(ws)
    assert len(rows) == 1
    assert rows[0] == {
        "chemical": "Paracetamol",
        "presentation": "500mg tab",
        "brand": "Panadol",
        "pharmacode": "1234",
        "nzmt_ctpp_id": "NZ001",
        "subsidy": "$0.00",
        "fully_subsidised": "Y",
        "language": "en-NZ",
    }


def test_pharmac_drugs_fetch_none_cursor_is_noop():
    src = PharmacDrugsSource()
    rows, cursor = src.fetch(None)
    assert rows == []
    assert cursor is None


def test_pharmac_drugs_registered():
    assert all_sources().get("pharmac_drugs") is PharmacDrugsSource


# ---------------------------------------------------------------------------
# fda_ndc
# ---------------------------------------------------------------------------

def test_fda_ndc_row_schema():
    row = fda_ndc_row({
        "PRODUCTNDC": "1234-5678", "NONPROPRIETARYNAME": "Acetaminophen",
        "PROPRIETARYNAME": "Tylenol", "PROPRIETARYNAMESUFFIX": "Extra Strength",
        "LABELERNAME": "J&J", "PRODUCTTYPENAME": "HUMAN OTC DRUG",
        "DOSAGEFORMNAME": "TABLET", "ROUTENAME": "ORAL",
        "MARKETINGCATEGORYNAME": "OTC MONOGRAPH", "APPLICATIONNUMBER": "",
        "SUBSTANCENAME": "ACETAMINOPHEN", "ACTIVE_NUMERATOR_STRENGTH": "500",
        "ACTIVE_INGRED_UNIT": "mg/1", "PHARM_CLASSES": "", "DEASCHEDULE": "",
        "MARKETINGSTART": "20200101", "MARKETINGEND": "",
        "LISTING_RECORD_CERTIFIED_THROUGH": "20241231",
    })
    assert row == {
        "product_ndc": "1234-5678",
        "generic_name": "Acetaminophen",
        "brand_name": "Tylenol",
        "brand_name_suffix": "Extra Strength",
        "labeler_name": "J&J",
        "product_type": "HUMAN OTC DRUG",
        "dosage_form": "TABLET",
        "route": ["ORAL"],
        "marketing_category": "OTC MONOGRAPH",
        "application_number": "",
        "substance_name": "ACETAMINOPHEN",
        "active_numerator_strength": "500",
        "active_ingred_unit": "mg/1",
        "pharm_classes": "",
        "deaschedule": "",
        "marketing_start_date": "20200101",
        "marketing_end_date": "",
        "listing_record_certified_through": "20241231",
    }


def test_fda_ndc_row_empty_route_is_empty_list():
    row = fda_ndc_row({"ROUTENAME": ""})
    assert row["route"] == []


def test_fda_ndc_fetch_none_cursor_is_noop():
    src = FdaNdcSource()
    rows, cursor = src.fetch(None)
    assert rows == []
    assert cursor is None


def test_fda_ndc_registered():
    assert all_sources().get("fda_ndc") is FdaNdcSource


# ---------------------------------------------------------------------------
# fda_orange_book
# ---------------------------------------------------------------------------

def test_fda_orange_book_parse_products_schema():
    import zipfile
    import io as _io

    buf = _io.BytesIO()
    text = (
        "Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~"
        "Product_No~TE_Code~Approval_Date~RLD~RS~Type~Applicant_Full_Name\n"
        "ASPIRIN~TABLET;ORAL~BAYER ASPIRIN~BAYER~325MG~OTC~012345~001~AB~"
        "Approved Prior to Jan 1, 1982~Yes~Yes~RX~Bayer HealthCare LLC\n"
    )
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("products.txt", text)

    rows = list(_parse_products(buf.getvalue()))
    assert rows == [{
        "ingredient": "ASPIRIN",
        "dosage_form": "TABLET",
        "route": "ORAL",
        "trade_name": "BAYER ASPIRIN",
        "applicant": "BAYER",
        "strength": "325MG",
        "appl_type": "OTC",
        "appl_no": "012345",
        "product_no": "001",
        "te_code": "AB",
        "approval_date": "Approved Prior to Jan 1, 1982",
        "rld": "Yes",
        "rs": "Yes",
        "drug_type": "RX",
        "applicant_full_name": "Bayer HealthCare LLC",
    }]


def test_fda_orange_book_fetch_none_cursor_is_noop():
    src = FdaOrangeBookSource()
    rows, cursor = src.fetch(None)
    assert rows == []
    assert cursor is None


def test_fda_orange_book_registered():
    assert all_sources().get("fda_orange_book") is FdaOrangeBookSource


# ---------------------------------------------------------------------------
# ema_epar
# ---------------------------------------------------------------------------

def test_ema_map_column_matches_by_substring():
    assert _map_column("Medicine name") == "medicine_name"
    assert _map_column("International non-proprietary name (INN) / common name") == "inn_common_name"
    assert _map_column("something unrelated") is None


def test_ema_parse_xlsx_schema():
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Content type: medicine"])
    ws.append([None])
    ws.append(["Medicine name", "Active substance", "Authorisation status", "URL", "Generic"])
    ws.append(["Aspirin", "acetylsalicylic acid", "Authorised", "https://ema/x", "yes"])
    buf_path = "/tmp/_ema_test.xlsx" if False else None

    import io as _io
    buf = _io.BytesIO()
    wb.save(buf)

    rows = list(_parse_xlsx(buf.getvalue()))
    assert rows == [{
        "medicine_name": "Aspirin",
        "inn_common_name": "",
        "active_substance": "acetylsalicylic acid",
        "product_number": "",
        "authorisation_status": "Authorised",
        "atc_code": "",
        "therapeutic_area": "",
        "date_of_authorisation": "",
        "generic": "yes",
        "orphan": "",
        "biosimilar": "",
        "url": "https://ema/x",
    }]


def test_ema_epar_fetch_none_cursor_is_noop():
    src = EmaEparSource()
    rows, cursor = src.fetch(None)
    assert rows == []
    assert cursor is None


def test_ema_epar_registered():
    assert all_sources().get("ema_epar") is EmaEparSource


# ---------------------------------------------------------------------------
# kegg_drugs
# ---------------------------------------------------------------------------

def test_kegg_parse_names_strips_tags():
    names, tags = _parse_names("Aspirin (JAN/USP/INN); Acetylsalicylic acid (JP18)")
    assert names == ["Aspirin", "Acetylsalicylic acid"]
    assert tags == {"Aspirin": ["JAN/USP/INN"], "Acetylsalicylic acid": ["JP18"]}


def test_kegg_parse_kegg_record_schema():
    text = (
        "ENTRY       D00109                      Drug\n"
        "NAME        Aspirin (JAN/USP/INN);\n"
        "            Acetylsalicylic acid (JP18)\n"
        "FORMULA     C9H8O4\n"
        "CLASS       Analgesic\n"
        "            Antipyretic\n"
    )
    parsed = _parse_kegg_record(text)
    assert parsed["kegg_id"] == "D00109"
    assert parsed["formula"] == "C9H8O4"
    assert parsed["drug_class"] == ["Analgesic", "Antipyretic"]
    assert "Aspirin (JAN/USP/INN);" in parsed["names_block"]


def test_kegg_split_records():
    text = "ENTRY D1\nNAME A\n///\nENTRY D2\nNAME B\n///\n"
    records = _split_records(text)
    assert len(records) == 2
    assert records[0].startswith("ENTRY D1")
    assert records[1].startswith("ENTRY D2")


def test_kegg_drugs_fetch_walks_batches_and_stops():
    src = KeggDrugsSource()
    src.throttle.wait = lambda: None
    src._kegg_ids = ["D00001", "D00002"]
    src._kegg_name_raw = {"D00001": "One (INN)", "D00002": "Two (INN)"}
    src._fetch_batch = lambda ids: (
        "ENTRY       D00001                      Drug\n"
        "NAME        One (INN)\n"
        "FORMULA     C1\n"
        "///\n"
        "ENTRY       D00002                      Drug\n"
        "NAME        Two (INN)\n"
        "FORMULA     C2\n"
        "///\n"
    )
    rows, cursor = src.fetch(0)
    assert cursor is None  # BATCH(10) > len(ids), everything fetched in one page
    assert [r["kegg_id"] for r in rows] == ["D00001", "D00002"]
    assert rows[0]["formula"] == "C1"


def test_kegg_drugs_fetch_falls_back_to_minimal_row_on_empty_response():
    src = KeggDrugsSource()
    src.throttle.wait = lambda: None
    src._kegg_ids = ["D00001"]
    src._kegg_name_raw = {"D00001": "One (INN)"}
    src._fetch_batch = lambda ids: ""
    rows, cursor = src.fetch(0)
    assert rows == [{
        "kegg_id": "D00001", "names": ["One"], "tags": {"One": ["INN"]},
        "formula": "", "drug_class": [], "name_raw": "One (INN)",
    }]
    assert cursor is None


def test_kegg_drugs_fetch_returns_none_past_end():
    src = KeggDrugsSource()
    src._kegg_ids = ["D00001"]
    rows, cursor = src.fetch(5)
    assert rows == []
    assert cursor is None


def test_kegg_drugs_registered():
    assert all_sources().get("kegg_drugs") is KeggDrugsSource


# ---------------------------------------------------------------------------
# drugbank_open
# ---------------------------------------------------------------------------

def test_drugbank_parse_row_schema():
    row = drugbank_parse_row({
        "DrugBank ID": "DB00945", "Name": "Aspirin", "CAS Number": "50-78-2",
        "UNII": "R16CO5Y76E", "Synonyms": "Acetylsalicylic acid|ASA",
        "Standard InChI": "InChI=1S/...", "Standard InChI Key": "BSYNRYMUTXBXSQ",
        "SMILES": "CC(=O)OC1=CC=CC=C1C(=O)O", "Formula": "C9H8O4",
        "Groups": "approved; over the counter",
        "ATC Codes": "N02BA01|A01AD05", "Description": "desc",
        "Indication": "indication", "Pharmacodynamics": "pd",
        "Mechanism of Action": "moa", "Food Interactions": "Take with food",
        "Categories": "Analgesics; Antipyretics",
    })
    assert row == {
        "drugbank_id": "DB00945",
        "name": "Aspirin",
        "cas_number": "50-78-2",
        "unii": "R16CO5Y76E",
        "synonyms": ["Acetylsalicylic acid", "ASA"],
        "standard_inchi": "InChI=1S/...",
        "standard_inchi_key": "BSYNRYMUTXBXSQ",
        "smiles": "CC(=O)OC1=CC=CC=C1C(=O)O",
        "formula": "C9H8O4",
        "groups": ["approved", "over the counter"],
        "atc_codes": ["N02BA01", "A01AD05"],
        "description": "desc",
        "indication": "indication",
        "pharmacodynamics": "pd",
        "mechanism_of_action": "moa",
        "food_interactions": ["Take with food"],
        "categories": ["Analgesics", "Antipyretics"],
    }


def test_drugbank_open_fetch_reads_csv_path(tmp_path):
    csv_text = "DrugBank ID,Name\nDB00945,Aspirin\n"
    p = tmp_path / "drugbank.csv"
    p.write_text(csv_text, encoding="utf-8")

    src = DrugbankOpenSource()
    src._csv_path = str(p)
    rows, cursor = src.fetch(0)
    assert cursor is None
    assert len(rows) == 1
    assert rows[0]["drugbank_id"] == "DB00945"
    assert rows[0]["name"] == "Aspirin"


def test_drugbank_open_fetch_none_cursor_is_noop():
    src = DrugbankOpenSource()
    rows, cursor = src.fetch(None)
    assert rows == []
    assert cursor is None


def test_drugbank_open_registered():
    assert all_sources().get("drugbank_open") is DrugbankOpenSource


# ---------------------------------------------------------------------------
# batch6 registration roundup
# ---------------------------------------------------------------------------

def test_batch6_scrapers_are_registered():
    reg = all_sources()
    assert reg.get("aemps_drugs") is AempsDrugsSource
    assert reg.get("ansm_drugs") is AnsmDrugsSource
    assert reg.get("anvisa_drugs") is AnvisaDrugsSource
    assert reg.get("cbg_drugs") is CbgDrugsSource
    assert reg.get("isp_drugs") is IspDrugsSource
    assert reg.get("pharmac_drugs") is PharmacDrugsSource
    assert reg.get("fda_ndc") is FdaNdcSource
    assert reg.get("fda_orange_book") is FdaOrangeBookSource
    assert reg.get("ema_epar") is EmaEparSource
    assert reg.get("kegg_drugs") is KeggDrugsSource
    assert reg.get("drugbank_open") is DrugbankOpenSource
