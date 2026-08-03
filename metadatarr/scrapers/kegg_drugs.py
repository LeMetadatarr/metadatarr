"""KEGG Drug database scraper — migrated onto the engine.

Fetches all KEGG Drug entries via the KEGG REST API (no authentication
required):

  1. ``GET https://rest.kegg.jp/list/drug`` -> tab-separated
     ``KEGG_ID\\tnames_raw`` list of every entry (fetched once per process
     and cached on the source instance — it's a cheap ~400 KB list, but
     re-fetching it on every batch would be wasteful).
  2. Batches of up to 10 IDs against
     ``GET https://rest.kegg.jp/get/D00001+D00002+...`` for full flat-text
     records containing NAME, FORMULA, CLASS sections.

The cursor is a plain integer offset into the (stable-ordered) full ID list;
each :meth:`fetch` call handles one batch of :data:`BATCH` IDs.

Schema per row:
  kegg_id, names[], tags{name: [tag,...]}, formula, drug_class[], name_raw

DEVIATION (resume-granularity): the original tracked completion per-ID in a
``done_ids`` checkpoint set, so on restart it could retry exactly the IDs
that were requested in a batch but never appeared in the KEGG response (a
partial/short response). The engine's cursor is an offset into the ID list,
so on restart it resumes at the next un-fetched *batch*; the small handful of
IDs that were requested-but-missing from a completed batch's response will
not be individually retried within the same run, only re-attempted if that
batch itself is re-fetched (i.e. a restart before the batch's cursor was
checkpointed). ``id_field="kegg_id"`` still gives the same per-row dedup as
before (rows are never re-written), it is only the *retry* precision for
never-appeared IDs that coarsens from per-ID to per-batch.

Run it::

    python -m metadatarr.scrapers kegg_drugs [--output DIR] [--delay SECS]
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from metadatarr.scrapers.engine import Page, Source, register, run_cli

LIST_URL = "https://rest.kegg.jp/list/drug"
GET_URL = "https://rest.kegg.jp/get/{ids}"
BATCH = 10

_TAG_RE = re.compile(r"\(([^)]+)\)")


def _parse_names(names_raw: str) -> Tuple[List[str], Dict[str, List[str]]]:
    """Parse the names_raw string (may be multi-line with semicolons) into
    a list of bare names and a tag mapping.

    Returns:
        names: list of name strings with tags stripped
        tags:  {name_bare: [tag, ...]}
    """
    names: List[str] = []
    tags: Dict[str, List[str]] = {}
    for part in re.split(r"[;\n]", names_raw):
        part = part.strip()
        if not part:
            continue
        found_tags = _TAG_RE.findall(part)
        bare = _TAG_RE.sub("", part).strip().rstrip("/").strip()
        if not bare:
            continue
        names.append(bare)
        if found_tags:
            tags[bare] = found_tags
    return names, tags


def _parse_kegg_record(text: str) -> Dict[str, object]:
    """Parse a single KEGG flat-text drug record.

    Returns dict with keys: kegg_id, names_block, formula, drug_class.
    """
    kegg_id = ""
    names_lines: List[str] = []
    formula = ""
    drug_class: List[str] = []
    current_section = ""

    for line in text.splitlines():
        if not line:
            continue
        if not line.startswith(" "):
            section = line[:12].rstrip()
            rest = line[12:].strip()
            current_section = section
            if section == "ENTRY":
                kegg_id = rest.split()[0] if rest else ""
            elif section == "NAME":
                names_lines = [rest] if rest else []
            elif section == "FORMULA":
                formula = rest
            elif section == "CLASS":
                if rest:
                    drug_class = [rest]
        else:
            rest = line.strip()
            if current_section == "NAME":
                names_lines.append(rest)
            elif current_section == "CLASS":
                if rest:
                    drug_class.append(rest)

    return {
        "kegg_id": kegg_id,
        "names_block": "\n".join(names_lines),
        "formula": formula,
        "drug_class": [c.rstrip(";").strip() for c in drug_class if c.strip()],
    }


def _split_records(text: str) -> List[str]:
    """Split a multi-record KEGG response into individual records."""
    records = []
    current: List[str] = []
    for line in text.splitlines():
        if line.startswith("///"):
            if current:
                records.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        records.append("\n".join(current))
    return [r for r in records if r.strip()]


@register
class KeggDrugsSource(Source):
    name = "kegg_drugs"
    id_field = "kegg_id"
    default_delay = 0.5

    def initial_cursor(self) -> int:
        return 0

    def session(self):
        if not hasattr(self, "_kegg_session") or self._kegg_session is None:
            try:
                from unblock_requests import CloudflareSession
                s = CloudflareSession()
            except Exception:
                import requests
                s = requests.Session()
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
                "Accept": "text/plain, */*",
            })
            self._kegg_session = s
        return self._kegg_session

    def _fetch_list(self) -> List[Tuple[str, str]]:
        r = self.session().get(LIST_URL, timeout=60)
        r.raise_for_status()
        entries = []
        for line in r.text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                entries.append((parts[0].strip(), parts[1].strip()))
        return entries

    def _ids(self) -> List[str]:
        if not hasattr(self, "_kegg_ids"):
            entries = self._fetch_list()
            self._kegg_name_raw = {kid: nr for kid, nr in entries}
            self._kegg_ids = [kid for kid, _ in entries]
        return self._kegg_ids

    def _fetch_batch(self, ids: List[str]) -> str:
        self.throttle.wait()
        url = GET_URL.format(ids="+".join(ids))
        r = self.session().get(url, timeout=60)
        if r.status_code == 404:
            return ""
        r.raise_for_status()
        return r.text

    def fetch(self, cursor: int) -> Page:
        ids = self._ids()
        offset = int(cursor or 0)
        if offset >= len(ids):
            return [], None

        batch_ids = ids[offset:offset + BATCH]
        raw = self._fetch_batch(batch_ids)

        rows: List[dict] = []
        if not raw:
            for kid in batch_ids:
                name_raw = self._kegg_name_raw.get(kid, "")
                names, tags = _parse_names(name_raw)
                rows.append({
                    "kegg_id": kid,
                    "names": names,
                    "tags": tags,
                    "formula": "",
                    "drug_class": [],
                    "name_raw": name_raw,
                })
        else:
            for rec_text in _split_records(raw):
                parsed = _parse_kegg_record(rec_text)
                kid = parsed["kegg_id"]
                if not kid:
                    continue
                name_raw = self._kegg_name_raw.get(kid, parsed.get("names_block", ""))
                names, tags = _parse_names(parsed["names_block"] or name_raw)
                rows.append({
                    "kegg_id": kid,
                    "names": names,
                    "tags": tags,
                    "formula": parsed["formula"],
                    "drug_class": parsed["drug_class"],
                    "name_raw": name_raw,
                })

        next_cursor = offset + BATCH if offset + BATCH < len(ids) else None
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(KeggDrugsSource))
