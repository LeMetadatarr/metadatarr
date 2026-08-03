#!/usr/bin/env python3
"""
Build a unified drugs dataset (1 row per INN/active ingredient) from all
drug-related JSONL files in the metadatarr scrapers cache.

Usage:
    python build_unified_drugs.py [--output DIR]
"""

import argparse
import json
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize(s: str) -> str:
    """Lightweight normalisation: strip whitespace + lowercase."""
    if not s:
        return ""
    return s.strip().lower()


def load_jsonl(name: str, cache_dir: Path):
    """Yield dicts from {cache_dir}/{name}.jsonl, skipping malformed lines."""
    path = cache_dir / f"{name}.jsonl"
    if not path.exists():
        print(f"  [WARN] {path} not found — skipping", file=sys.stderr)
        return
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                pass
            if i % 10_000 == 0 and i:
                print(f"    … {name}: {i:,} rows read", flush=True)


def _empty_entry(inn: str) -> dict:
    return {
        "inn": inn,
        "chembl_id": None,
        "rxcui": None,
        "kegg_id": None,
        "pubchem_cid": None,
        "atc_codes": [],
        "atc_hierarchy": None,
        "max_phase": None,
        "molecule_type": None,
        "first_approval": None,
        "withdrawn": False,
        "usan_stem": None,
        "molecular_formula": None,
        "smiles": None,
        "inchi": None,
        "synonyms": [],
        "brand_names": [],
        "country_ids": {},
        "ipa": {},
        "arpabet": None,
        "categories": [],
        "tripsit_summary": None,
    }


def _add_brand(entry: dict, brand: str):
    if brand and brand not in entry["brand_names"]:
        entry["brand_names"].append(brand)


def _add_country_id(entry: dict, country: str, id_val: str):
    if id_val:
        entry["country_ids"].setdefault(country, [])
        if id_val not in entry["country_ids"][country]:
            entry["country_ids"][country].append(id_val)


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build(cache_dir: Path, output_dir: Path):
    canonical: dict[str, dict] = {}  # normalized_name → entry dict

    # ------------------------------------------------------------------
    # Step 1: ChEMBL anchor
    # ------------------------------------------------------------------
    print("Step 1: Loading ChEMBL …")
    for row in load_jsonl("chembl_drugs", cache_dir):
        pref = row.get("pref_name") or ""
        if not pref:
            continue
        key = normalize(pref)
        synonyms = [
            s["molecule_synonym"]
            for s in row.get("synonyms", [])
            if isinstance(s, dict) and s.get("molecule_synonym")
        ]
        entry = _empty_entry(pref)
        entry.update({
            "chembl_id": row.get("chembl_id"),
            "max_phase": row.get("max_phase"),
            "molecule_type": row.get("molecule_type"),
            "first_approval": row.get("first_approval"),
            "withdrawn": bool(row.get("withdrawn_flag", False)),
            "atc_codes": list(row.get("atc_classifications", [])),
            "usan_stem": row.get("usan_stem"),
            "pubchem_cid": row.get("pubchem_cid"),
            "inchi": row.get("inchi"),
            "smiles": row.get("canonical_smiles"),
            "synonyms": synonyms,
        })
        canonical[key] = entry
        # Index synonyms → same dict object
        for syn in synonyms:
            sk = normalize(syn)
            if sk and sk not in canonical:
                canonical[sk] = entry

    print(f"  ChEMBL anchor: {len(set(id(v) for v in canonical.values())):,} unique entries")

    # ------------------------------------------------------------------
    # Step 2: RxNorm (IN / PIN only)
    # ------------------------------------------------------------------
    print("Step 2: Loading RxNorm …")
    for row in load_jsonl("rxnorm_drugs", cache_dir):
        if row.get("tty") not in ("IN", "PIN"):
            continue
        name = row.get("name") or ""
        if not name:
            continue
        key = normalize(name)
        if key in canonical:
            e = canonical[key]
            if not e["rxcui"]:
                e["rxcui"] = row.get("rxcui")
            if not e["atc_codes"] and row.get("atc_codes"):
                e["atc_codes"] = list(row["atc_codes"])
        else:
            e = _empty_entry(name)
            e["rxcui"] = row.get("rxcui")
            e["atc_codes"] = list(row.get("atc_codes", []))
            canonical[key] = e

    print(f"  After RxNorm: {len(set(id(v) for v in canonical.values())):,} unique entries")

    # ------------------------------------------------------------------
    # Step 3: WHO ATC (5th-level only = single substance)
    # ------------------------------------------------------------------
    print("Step 3: Loading WHO ATC …")
    for row in load_jsonl("who_atc", cache_dir):
        atc_code = row.get("atc_code", "")
        if len(atc_code) != 7:
            continue
        name = row.get("name") or ""
        if not name:
            continue
        key = normalize(name)
        hierarchy = {
            "level1": {"code": row.get("level1_code"), "name": row.get("level1_name")},
            "level2": {"code": row.get("level2_code"), "name": row.get("level2_name")},
            "level3": {"code": row.get("level3_code"), "name": row.get("level3_name")},
            "level4": {"code": row.get("level4_code"), "name": row.get("level4_name")},
        }
        if key not in canonical:
            e = _empty_entry(name)
            e["atc_codes"] = [atc_code]
            canonical[key] = e
        else:
            e = canonical[key]
            if atc_code not in e["atc_codes"]:
                e["atc_codes"].append(atc_code)
        if not e.get("atc_hierarchy"):
            e["atc_hierarchy"] = hierarchy

    print(f"  After WHO ATC: {len(set(id(v) for v in canonical.values())):,} unique entries")

    # ------------------------------------------------------------------
    # Step 4: KEGG IDs
    # ------------------------------------------------------------------
    print("Step 4: Loading KEGG …")
    for row in load_jsonl("kegg_drugs", cache_dir):
        names = row.get("names", [])
        for name in names:
            key = normalize(name)
            if key in canonical:
                e = canonical[key]
                if not e["kegg_id"]:
                    e["kegg_id"] = row.get("kegg_id")
                if not e["molecular_formula"]:
                    e["molecular_formula"] = row.get("formula")
                break

    # ------------------------------------------------------------------
    # Step 5: EMA EPAR
    # ------------------------------------------------------------------
    print("Step 5: Loading EMA EPAR …")
    for row in load_jsonl("ema_epar", cache_dir):
        inn = (row.get("inn_common_name") or row.get("active_substance") or "").strip()
        if not inn:
            continue
        key = normalize(inn)
        if key not in canonical:
            e = _empty_entry(inn)
            if row.get("atc_code"):
                e["atc_codes"] = [row["atc_code"]]
            canonical[key] = e
        else:
            e = canonical[key]
        if row.get("product_number"):
            _add_country_id(e, "EU", str(row["product_number"]))

    print(f"  After EMA EPAR: {len(set(id(v) for v in canonical.values())):,} unique entries")

    # ------------------------------------------------------------------
    # Step 6: Country datasets → brand names + registration IDs
    # ------------------------------------------------------------------
    print("Step 6: Country registration datasets …")

    # --- USA: FDA NDC ---
    print("  fda_ndc …")
    for row in load_jsonl("fda_ndc", cache_dir):
        inn_raw = row.get("substance_name") or row.get("generic_name") or ""
        # substance_name can be semicolon-separated
        for inn in inn_raw.split(";"):
            inn = inn.strip()
            key = normalize(inn)
            if key in canonical:
                _add_brand(canonical[key], row.get("brand_name", "").strip())
                _add_country_id(canonical[key], "US", row.get("product_ndc"))
                break

    # --- USA: FDA Orange Book ---
    print("  fda_orange_book …")
    for row in load_jsonl("fda_orange_book", cache_dir):
        inn = (row.get("ingredient") or "").strip()
        key = normalize(inn)
        if key in canonical:
            _add_brand(canonical[key], (row.get("trade_name") or "").strip())
            _add_country_id(canonical[key], "US", row.get("appl_no"))

    # --- France: ANSM ---
    print("  ansm_drugs …")
    for row in load_jsonl("ansm_drugs", cache_dir):
        substances = row.get("substances", [])
        brand = (row.get("specialite_name") or "").strip()
        cis = row.get("cis_code")
        matched = False
        for sub in substances:
            if isinstance(sub, dict):
                sub_name = sub.get("name") or ""
            else:
                sub_name = str(sub)
            key = normalize(sub_name)
            if key in canonical:
                _add_brand(canonical[key], brand)
                _add_country_id(canonical[key], "FR", str(cis) if cis else None)
                matched = True
                break

    # --- Spain: AEMPS ---
    print("  aemps_drugs …")
    for row in load_jsonl("aemps_drugs", cache_dir):
        inn = (row.get("vtm") or "").strip()
        key = normalize(inn)
        if key in canonical:
            _add_brand(canonical[key], (row.get("nombre") or "").strip())
            _add_country_id(canonical[key], "ES", row.get("nregistro"))

    # --- Brazil: ANVISA ---
    print("  anvisa_drugs …")
    for row in load_jsonl("anvisa_drugs", cache_dir):
        inn = (row.get("principio_ativo") or "").strip()
        key = normalize(inn)
        if key in canonical:
            _add_brand(canonical[key], (row.get("nome_produto") or "").strip())
            _add_country_id(canonical[key], "BR", row.get("numero_registro"))

    # --- Turkey: TITCK ---
    print("  titck_drugs …")
    for row in load_jsonl("titck_drugs", cache_dir):
        inn = (row.get("atc_adi") or "").strip()
        key = normalize(inn)
        if key in canonical:
            _add_brand(canonical[key], (row.get("ilac_adi") or "").strip())
            _add_country_id(canonical[key], "TR", str(row["barkod"]) if row.get("barkod") else None)

    # --- Switzerland: Swissmedic (heilmittelcode = ATC, match by ATC) ---
    print("  swissmedic_drugs …")
    # Build ATC → entry index for swissmedic
    atc_index: dict[str, list[dict]] = {}
    for e in set(id(v) for v in canonical.values()):
        pass  # just avoiding re-indexing; do it simply
    atc_to_entries: dict[str, list] = {}
    for e in {id(v): v for v in canonical.values()}.values():
        for atc in e.get("atc_codes", []):
            atc_to_entries.setdefault(atc, []).append(e)
    for row in load_jsonl("swissmedic_drugs", cache_dir):
        atc = (row.get("heilmittelcode") or "").strip()
        brand = (row.get("bezeichnung") or "").strip()
        zul = row.get("zulassungsnummer")
        for e in atc_to_entries.get(atc, []):
            _add_brand(e, brand)
            _add_country_id(e, "CH", str(zul) if zul else None)

    # --- Netherlands: CBG ---
    print("  cbg_drugs …")
    for row in load_jsonl("cbg_drugs", cache_dir):
        subs = row.get("werkzamestoffen") or ""
        brand = (row.get("productnaam") or "").strip()
        reg = row.get("registratienummer")
        atc = (row.get("atc") or "").strip()
        matched = False
        # Try substance name first
        for sub in (subs if isinstance(subs, list) else [subs]):
            key = normalize(str(sub))
            if key in canonical:
                _add_brand(canonical[key], brand)
                _add_country_id(canonical[key], "NL", str(reg) if reg else None)
                matched = True
                break
        if not matched and atc:
            for e in atc_to_entries.get(atc, []):
                _add_brand(e, brand)
                _add_country_id(e, "NL", str(reg) if reg else None)

    # --- Sweden: FASS (no INN — skip matching) ---
    # fass_drugs has no reliable INN field; skip

    # --- New Zealand: PHARMAC ---
    print("  pharmac_drugs …")
    for row in load_jsonl("pharmac_drugs", cache_dir):
        inn = (row.get("chemical") or "").strip()
        key = normalize(inn)
        if key in canonical:
            _add_brand(canonical[key], (row.get("brand") or "").strip())
            _add_country_id(canonical[key], "NZ", str(row["pharmacode"]) if row.get("pharmacode") else None)

    # --- Japan: PMDA ---
    print("  pmda_drugs …")
    for row in load_jsonl("pmda_drugs", cache_dir):
        inn = (row.get("nonproprietary_name") or "").strip()
        key = normalize(inn)
        if key in canonical:
            _add_brand(canonical[key], (row.get("brand_name") or "").strip())

    # --- Chile: ISP (no INN — skip) ---

    # --- Argentina: ANMAT ---
    print("  anmat_drugs …")
    for row in load_jsonl("anmat_drugs", cache_dir):
        inn = (row.get("nombre_generico") or "").strip()
        key = normalize(inn)
        if key in canonical:
            _add_brand(canonical[key], (row.get("nombre_comercial") or "").strip())
            _add_country_id(canonical[key], "AR", row.get("numero_certificado"))

    # --- Russia: GRLS ---
    print("  grls_drugs …")
    for row in load_jsonl("grls_drugs", cache_dir):
        inn = (row.get("inn_mnn") or "").strip()
        key = normalize(inn)
        if key in canonical:
            _add_brand(canonical[key], (row.get("trade_name") or "").strip())
            _add_country_id(canonical[key], "RU", row.get("reg_number"))

    # --- Italy: CODIFA (no INN — skip) ---

    # --- OpenFDA labels (extra brand name source) ---
    print("  openfda_labels …")
    for row in load_jsonl("openfda_labels", cache_dir):
        inn = (row.get("generic_name") or row.get("substance_name") or "").strip()
        key = normalize(inn)
        if key in canonical:
            _add_brand(canonical[key], (row.get("brand_name") or "").strip())

    print(f"  After country datasets: {len(set(id(v) for v in canonical.values())):,} unique entries")

    # ------------------------------------------------------------------
    # Step 7: TripSit + Erowid (add new psychoactive entries)
    # ------------------------------------------------------------------
    print("Step 7: TripSit + Erowid …")
    for row in load_jsonl("tripsit_drugs", cache_dir):
        name = row.get("pretty_name") or row.get("slug") or ""
        if not name:
            continue
        key = normalize(name)
        if key not in canonical:
            e = _empty_entry(name)
            canonical[key] = e
            # Index aliases
            for alias in row.get("aliases", []):
                ak = normalize(alias)
                if ak and ak not in canonical:
                    canonical[ak] = e
        else:
            e = canonical[key]
        e["categories"] = list(row.get("categories", []))
        props = row.get("properties") or {}
        e["tripsit_summary"] = props.get("summary") or row.get("summary")

    for row in load_jsonl("erowid_substances", cache_dir):
        name = row.get("name") or ""
        if not name:
            continue
        key = normalize(name)
        if key not in canonical:
            e = _empty_entry(name)
            canonical[key] = e
            for alias in row.get("other_names", []):
                ak = normalize(alias)
                if ak and ak not in canonical:
                    canonical[ak] = e
        else:
            e = canonical[key]
        if row.get("family") and not e["categories"]:
            e["categories"] = [row["family"]]
        if not e["tripsit_summary"] and row.get("description"):
            e["tripsit_summary"] = row["description"]

    # ------------------------------------------------------------------
    # Step 8: Pronunciations
    # ------------------------------------------------------------------
    print("Step 8: Pronunciations …")
    for row in load_jsonl("wiktionary_pronunciations", cache_dir):
        key = normalize(row.get("term", ""))
        if key in canonical:
            lang = row.get("language") or "und"
            ipa_list = row.get("ipa", [])
            if ipa_list:
                canonical[key].setdefault("ipa", {})[lang] = ipa_list

    for row in load_jsonl("cmu_pronunciations", cache_dir):
        key = normalize(row.get("term", ""))
        if key in canonical:
            if not canonical[key].get("arpabet"):
                canonical[key]["arpabet"] = row.get("arpabet")

    # ------------------------------------------------------------------
    # Step 9: Deduplicate and write
    # ------------------------------------------------------------------
    print("Step 9: Deduplicating and writing …")
    seen_ids: set = set()
    rows_out = []
    for entry in canonical.values():
        uid = entry.get("chembl_id") or entry.get("rxcui") or entry.get("inn")
        if uid not in seen_ids:
            seen_ids.add(uid)
            # Clean up empty brand names
            entry["brand_names"] = [b for b in entry["brand_names"] if b]
            rows_out.append(entry)

    output_path = output_dir / "unified_drugs.jsonl"
    with open(output_path, "w", encoding="utf-8") as fh:
        for row in rows_out:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------
    total = len(rows_out)
    has_chembl = sum(1 for r in rows_out if r.get("chembl_id"))
    has_atc = sum(1 for r in rows_out if r.get("atc_codes"))
    has_brand = sum(1 for r in rows_out if r.get("brand_names"))
    has_ipa = sum(1 for r in rows_out if r.get("ipa"))

    print()
    print("=" * 50)
    print(f"Output: {output_path}")
    print(f"Total unique drugs:        {total:>8,}")
    print(f"  With ChEMBL ID:          {has_chembl:>8,}")
    print(f"  With ATC code:           {has_atc:>8,}")
    print(f"  With brand names:        {has_brand:>8,}")
    print(f"  With IPA pronunciation:  {has_ipa:>8,}")
    print("=" * 50)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build unified drugs JSONL dataset")
    parser.add_argument(
        "--output",
        default=os.path.expanduser("~/.cache/metadatarr/scrapers/"),
        help="Directory to write unified_drugs.jsonl (default: ~/.cache/metadatarr/scrapers/)",
    )
    args = parser.parse_args()

    cache_dir = Path(os.path.expanduser("~/.cache/metadatarr/scrapers/"))
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    build(cache_dir, output_dir)
