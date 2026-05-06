"""Identify duplicate and distinct-version files in a local media library.

User story: "I have a folder full of Blade Runner rips acquired over the
years. Some are duplicates (same cut, different encode settings). Others are
genuinely different versions — the Director's Cut, the Final Cut, the
theatrical. I want the library to keep exactly one file per canonical cut and
flag real duplicates for deletion, without accidentally discarding a rare cut
I only have one copy of."

This script shows how to:
  1. Parse filenames to extract title / year / cut hints
  2. Build Signals bags (with variant_kind + runtime if known)
  3. Use signal_hash to bucket files by canonical version
  4. Within each bucket: sort by quality score, mark best-keep + candidates
     for deletion
  5. Print a decision table (keep / delete / needs-review)

No network required — this is a pure offline signal-layer example.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from mediavocab import MediaType, VariantKind
from mediavocab.models.signals import Signals, signal_hash

# ---------------------------------------------------------------------------
# Simulated library — paths you'd normally get from os.walk or a Plex API
# ---------------------------------------------------------------------------

LIBRARY: List[Dict] = [
    # --- Blade Runner ---------------------------------------------------------
    {"path": "/media/movies/Blade Runner (1982) [Theatrical].mkv",    "size_mb": 8200},
    {"path": "/media/movies/Blade Runner (1982) [Theatrical].avi",    "size_mb": 1400},   # dupe, smaller
    {"path": "/media/movies/Blade Runner (1982) [Director's Cut].mkv","size_mb": 8400},
    {"path": "/media/movies/Blade Runner (1982) [Final Cut].mkv",     "size_mb": 28000},
    {"path": "/media/movies/Blade Runner (1982) [Final Cut] 1080p.mkv","size_mb": 14000}, # dupe of Final Cut
    {"path": "/media/movies/Blade Runner (1982) [Final Cut] 720p.mkv", "size_mb": 6200},  # dupe of Final Cut
    # --- Apocalypse Now -------------------------------------------------------
    {"path": "/media/movies/Apocalypse Now (1979) [Theatrical].mkv",  "size_mb": 18000},
    {"path": "/media/movies/Apocalypse Now (1979) [Redux].mkv",       "size_mb": 22000},
    {"path": "/media/movies/Apocalypse Now (1979).mkv",               "size_mb": 9000},   # ambiguous — no cut tag
]

# ---------------------------------------------------------------------------
# Runtime hints per (title, variant_kind) — in a real system you'd query
# dvdcompare or your scan tool.  Listed in seconds.
# ---------------------------------------------------------------------------

KNOWN_RUNTIMES: Dict[Tuple[str, VariantKind], int] = {
    ("Blade Runner", VariantKind.THEATRICAL): 6960,   # 116 min
    ("Blade Runner", VariantKind.DIRECTORS):  7080,   # 118 min
    ("Blade Runner", VariantKind.EXTENDED):   7140,   # 119 min — Final Cut maps here
    ("Apocalypse Now", VariantKind.THEATRICAL): 9300, # 155 min
    ("Apocalypse Now", VariantKind.EXTENDED): 11700,  # 195 min — Redux
}

# ---------------------------------------------------------------------------
# Filename → Signals
# ---------------------------------------------------------------------------

_TITLE_YEAR_RE = re.compile(r"^(.+?)\s+\((\d{4})\)")
_VARIANT_TAGS = {
    "theatrical":      VariantKind.THEATRICAL,
    "directors cut":   VariantKind.DIRECTORS,
    "director's cut":  VariantKind.DIRECTORS,
    "directors' cut":  VariantKind.DIRECTORS,
    "dc":              VariantKind.DIRECTORS,
    "final cut":       VariantKind.EXTENDED,   # Blade Runner: Final Cut = extended restoration
    "redux":           VariantKind.EXTENDED,
    "extended":        VariantKind.EXTENDED,
    "assembly cut":    VariantKind.EXTENDED,
    "special edition": VariantKind.EXTENDED,
}


def _parse(path: str) -> Signals:
    stem = Path(path).stem
    m = _TITLE_YEAR_RE.match(stem)
    title = m.group(1).strip() if m else stem
    year  = int(m.group(2)) if m else None

    lower = stem.lower()
    variant: Optional[VariantKind] = None
    for tag, kind in sorted(_VARIANT_TAGS.items(), key=lambda kv: -len(kv[0])):
        if tag in lower:
            variant = kind
            break

    runtime = None
    if variant and title:
        runtime = KNOWN_RUNTIMES.get((title, variant))

    return Signals(
        title=title,
        year=year,
        medium=MediaType.MOVIE,
        variant_kind=variant,
        runtime=float(runtime) if runtime else None,
    )


# ---------------------------------------------------------------------------
# Quality score — higher is better; used to pick the keeper within a bucket
# ---------------------------------------------------------------------------

def _quality(entry: dict) -> int:
    path  = entry["path"].lower()
    score = entry["size_mb"]   # larger file = higher quality encode baseline
    if ".mkv" in path:
        score += 5000          # prefer mkv container
    return score


# ---------------------------------------------------------------------------
# Decision table
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    path: str
    title: str
    year: Optional[int]
    variant: Optional[str]
    hash12: str
    size_mb: int
    action: str   # "KEEP", "DELETE", "REVIEW"
    reason: str


def main() -> None:
    # 1. Parse every path into a Signals bag
    entries = []
    for item in LIBRARY:
        sig = _parse(item["path"])
        h   = signal_hash(sig)
        entries.append({**item, "sig": sig, "hash": h})

    # 2. Group by hash
    buckets: Dict[str, List[dict]] = {}
    for e in entries:
        buckets.setdefault(e["hash"], []).append(e)

    # 3. Decide per bucket
    decisions: List[Decision] = []
    for h, group in buckets.items():
        sig = group[0]["sig"]
        title   = sig.title or "?"
        year    = sig.year
        variant = sig.variant_kind.value if sig.variant_kind else None

        if len(group) == 1:
            e = group[0]
            action = "KEEP"
            reason = "only copy of this cut"
            if variant is None:
                action = "REVIEW"
                reason = "no cut tag — confirm which version this is"
            decisions.append(Decision(
                path=e["path"], title=title, year=year, variant=variant,
                hash12=h[:12], size_mb=e["size_mb"], action=action, reason=reason,
            ))
        else:
            # Multiple files with the same canonical hash — keep best quality
            ranked = sorted(group, key=_quality, reverse=True)
            keeper = ranked[0]
            decisions.append(Decision(
                path=keeper["path"], title=title, year=year, variant=variant,
                hash12=h[:12], size_mb=keeper["size_mb"], action="KEEP",
                reason=f"best encode among {len(group)} duplicate(s)",
            ))
            for dup in ranked[1:]:
                decisions.append(Decision(
                    path=dup["path"], title=title, year=year, variant=variant,
                    hash12=h[:12], size_mb=dup["size_mb"], action="DELETE",
                    reason=f"duplicate of {Path(keeper['path']).name}",
                ))

    # 4. Print decision table
    print(f"\n{'Action':<8}  {'Cut':<22}  {'MB':>6}  Path")
    print(f"{'------':<8}  {'-'*22}  {'-'*6}  ----")
    for d in sorted(decisions, key=lambda x: (x.title, x.variant or "", x.action)):
        cut_label = f"{d.title} [{d.variant or '???'}]"
        print(f"{d.action:<8}  {cut_label:<22}  {d.size_mb:>6}  {d.path}")
        if d.action in ("DELETE", "REVIEW"):
            print(f"{'':8}  {'':22}  {'':6}  → {d.reason}")

    keep   = sum(1 for d in decisions if d.action == "KEEP")
    delete = sum(1 for d in decisions if d.action == "DELETE")
    review = sum(1 for d in decisions if d.action == "REVIEW")
    saved  = sum(d.size_mb for d in decisions if d.action == "DELETE")
    print(f"\n  {keep} keep  /  {delete} delete ({saved:,} MB freed)  /  {review} need review")
    print()


if __name__ == "__main__":
    main()
