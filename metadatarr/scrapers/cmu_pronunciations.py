"""CMU Pronouncing Dictionary drug-name extractor.

One-shot download of the CMU Pronouncing Dictionary (125k+ English words with
ARPAbet phonemes), cross-referenced against all drug names collected by the
*other* scrapers' JSONL datasets in the same output directory. This is a
single bulk download + cross-reference pass, not paginated, so it is modelled
as one page: :meth:`fetch` returns ``(all_rows, None)``.

Deviation: the engine's :meth:`~metadatarr.scrapers.engine.Source.fetch`
signature doesn't receive the output directory (only a cursor), but this
scraper needs it to scan sibling datasets. :meth:`run` is overridden to stash
it on ``self._output_dir`` before delegating to the engine loop — no other
behaviour changes.

Schema per row:
  term, arpabet, variant_num, source_file

Run it::

    python -m metadatarr.scrapers cmu_pronunciations [--output DIR]
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

from metadatarr.scrapers.engine import Source, register, run_cli

CMU_URL = "https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict"

_NAME_FIELDS = [
    "generic_name", "brand_name", "nome_produto", "pref_name",
    "ingredient", "trade_name", "inn", "drug_name", "term",
    "medicine_name", "inn_common_name", "active_substance",
]


def _load_cmu(output_dir: Path) -> Dict[str, List[str]]:
    """Download CMU dict and return {word_lower: [arpabet_string, ...]}."""
    import requests
    cache = output_dir / "cmudict.dict"
    if not cache.exists():
        s = requests.Session()
        s.headers["User-Agent"] = "Mozilla/5.0"
        r = s.get(CMU_URL, timeout=60)
        r.raise_for_status()
        cache.write_bytes(r.content)

    cmu: Dict[str, List[str]] = {}
    for line in cache.read_text("utf-8").splitlines():
        if line.startswith(";;;"):
            continue
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        # Handle variant entries: ASPIRIN(1), ASPIRIN(2)
        raw_word = parts[0]
        m = re.match(r"^([A-Za-z0-9'-]+?)(?:\((\d+)\))?$", raw_word)
        if not m:
            continue
        word = m.group(1).lower()
        arpabet = " ".join(parts[1:])
        cmu.setdefault(word, []).append(arpabet)
    return cmu


def _collect_drug_names(output_dir: Path, this_name: str) -> set:
    """Collect all known drug names from other scrapers' JSONL output."""
    names: set = set()
    for jsonl_file in output_dir.glob("*.jsonl"):
        if jsonl_file.stem == this_name:
            continue
        try:
            with open(jsonl_file) as f:
                for line in f:
                    try:
                        row = json.loads(line)
                        for field in _NAME_FIELDS:
                            val = row.get(field)
                            if isinstance(val, str) and val.strip():
                                names.add(val.strip().lower())
                        # Handle synonym lists
                        for syn in row.get("synonyms") or []:
                            if isinstance(syn, dict):
                                v = syn.get("name", "")
                            else:
                                v = str(syn)
                            if v.strip():
                                names.add(v.strip().lower())
                        for ai in row.get("active_ingredients") or []:
                            if isinstance(ai, dict):
                                v = ai.get("name", "") or ai.get("ingredient_name", "")
                                if v.strip():
                                    names.add(v.strip().lower())
                    except Exception:
                        pass
        except Exception:
            pass
    return names


@register
class CmuPronunciationsSource(Source):
    name = "cmu_pronunciations"
    id_field = ""
    default_delay = 0.0

    def initial_cursor(self) -> int:
        return 0


    def map_row(self, name: str, arpabet: str, variant_num: int, source_file: str) -> dict:
        return {
            "term": name,
            "arpabet": arpabet,
            "variant_num": variant_num,
            "source_file": source_file,
        }

    def fetch(self, cursor: int):
        if cursor is None:
            return [], None

        output_dir = getattr(self, "_output_dir", None)
        if output_dir is None:
            from metadatarr.scrapers._checkpoint import default_output_dir
            output_dir = default_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)

        cmu = _load_cmu(output_dir)
        drug_names = _collect_drug_names(output_dir, self.name)

        rows = []
        for name in sorted(drug_names):
            if name in cmu:
                for i, arpabet in enumerate(cmu[name]):
                    rows.append(self.map_row(name, arpabet, i + 1, "cmudict.dict"))
            else:
                # Try space-separated multi-word (e.g. "amoxicillin and clavulanate")
                parts = name.split()
                if len(parts) > 1:
                    part_arps = [cmu.get(p) for p in parts]
                    if all(part_arps):
                        combined = " ".join(a[0] for a in part_arps)
                        rows.append(self.map_row(name, combined, 1, "cmudict.dict+compound"))

        return rows, None


if __name__ == "__main__":
    raise SystemExit(run_cli(CmuPronunciationsSource))
