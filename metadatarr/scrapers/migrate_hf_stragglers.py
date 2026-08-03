"""Move remaining TigreGotico datasets (matched by name pattern) to LeData.

Complements migrate_hf_collections.py which only moved items already listed
in the 10 target collections. This script finds every remaining TigreGotico
dataset whose name signals it belongs to the LeData migration scope, moves it,
and adds it to the appropriate LeData collection.

Collection assignment is name-based:
  drugs-and-substances-* / *drugs* / *substances* / psychonautwiki-* / erowid-* /
  pubchem-* / openfda-* / who-atc / drugbank-* / rxnorm-*
      → drugs-and-substances collection

  media-metadata-*music* / *bandcamp* / *soundcloud* / *tidal* / *spotify* /
  *ytmusic* / *deezer* / *lastfm* / *metal* / *jazz* / *classical* / *prog*
      → music-metadata collection

  media-metadata-*anime* / *manga* / adult-metadata-hentai* / adult-metadata-hanime*
      → anime-and-manga-metadata collection

  *books* / *podcast* / *audiobook* / *librivox* / *gutenberg* / *openlibrary*
      → books-and-podcasts collection

  *games* / *steam* / *rawg* / *romhack* / *rom-hack*
      → games-metadata or rom-hacks-metadata

  *imdb* / *tmdb* / *movie* / *film* / *tvmaze* / *tv-show*
      → imdb-metadata or movie-metadata

  adult-metadata-*
      → adult-metadata collection

  anything else media-metadata-*
      → media-metadata collection (catch-all)

Usage:
    python migrate_hf_stragglers.py [--dry-run] [--token TOKEN]
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SOURCE_NS = "TigreGotico"
TARGET_NS = "LeData"
CKPT_PATH = Path.home() / ".cache" / "metadatarr" / "migrate_hf_stragglers_checkpoint.json"

# ---------------------------------------------------------------------------
# Name → collection slug mapping (use the slugs created by migrate_hf_collections.py)
# We look these up at runtime from the LeData collections list.
# ---------------------------------------------------------------------------

_DRUGS_KEYWORDS = {
    "drugs-and-substances", "psychonautwiki", "erowid", "pubchem",
    "openfda", "who-atc", "drugbank", "rxnorm", "tripsit", "substances",
    "wiktionary-pronunciations", "cmu-pronunciations", "dailymed",
    "chembl", "kegg", "ema-epar", "fda-ndc", "fda-orange",
    "health-canada", "aemps", "anmat", "ansm", "anvisa", "cbg",
    "codifa", "fass", "grls", "isp", "pharmac", "pmda", "swissmedic",
    "titck",
}

_MUSIC_KEYWORDS = {
    "music", "bandcamp", "soundcloud", "tidal", "spotify", "ytmusic",
    "deezer", "lastfm", "metal", "jazz", "classical", "prog",
    "audiodb", "musicbrainz", "musicbrainz-artists", "musicbrainz-releases",
    "platform-urls", "progarchives", "ytm", "ytmusic",
}

_ANIME_KEYWORDS = {
    "anime", "manga", "hentai", "hanime", "anilist", "jikan", "mal-anime",
}

_BOOKS_KEYWORDS = {
    "book", "podcast", "audiobook", "librivox", "gutenberg", "openlibrary",
    "listennotes", "podcastindex",
}

_GAMES_KEYWORDS = {"games", "steam", "rawg", "game"}
_ROMHACKS_KEYWORDS = {"romhack", "rom-hack", "rom_hack", "fanedits", "fanedit"}
_IMDB_KEYWORDS = {"imdb", "tmdb"}
_MOVIE_KEYWORDS = {"movie", "film", "tvmaze", "tv-show", "tv_show", "tvseries"}
_ADULT_KEYWORDS = {
    "adult", "boobpedia", "freeones", "iafd", "stashdb", "thenude",
    "performer", "hentai", "hanime",
}
_WIKIDATA_KEYWORDS = {"wikidata", "wikidata-entities"}
_RADIO_KEYWORDS = {"radiobrowser", "radio"}


def _classify(repo_name: str) -> str:
    """Return collection key for a repo name (lowercased, without org prefix)."""
    n = repo_name.lower().replace("_", "-")
    # Drugs wins over adult (erowid-substances, erowid-experiences are drug data)
    if any(k in n for k in _DRUGS_KEYWORDS):
        return "drugs"
    # Anime wins over adult for mal-anime, hentai when combined with anime keywords
    if any(k in n for k in _ANIME_KEYWORDS) and ("anime" in n or "manga" in n):
        return "anime"
    if any(k in n for k in _ADULT_KEYWORDS):
        return "adult"
    if any(k in n for k in _ROMHACKS_KEYWORDS):
        return "romhacks"
    if any(k in n for k in _GAMES_KEYWORDS):
        return "games"
    if any(k in n for k in _BOOKS_KEYWORDS):
        return "books"
    if any(k in n for k in _IMDB_KEYWORDS):
        return "imdb"
    if any(k in n for k in _MOVIE_KEYWORDS):
        return "movie"
    if any(k in n for k in _MUSIC_KEYWORDS):
        return "music"
    return "media"  # catch-all


def _is_in_scope(repo_id: str) -> bool:
    """True if this TigreGotico dataset belongs in the LeData migration scope."""
    n = repo_id.removeprefix(f"{SOURCE_NS}/").lower().replace("_", "-")
    # Anything with these prefixes is clearly in scope
    if n.startswith(("media-metadata-", "adult-metadata-", "drugs-and-substances-")):
        return True
    # Known standalone names that belong in scope
    in_scope_names = {
        "substances-catalog-xrefs", "tripsit-drugs", "psychonautwiki-substances",
        "erowid-substances", "erowid-experiences", "psychonautwiki-reagents",
        "psychonautwiki-reagent-results", "pubchem-compounds", "openfda-labels",
        "who-atc", "drugbank-open", "psychonautwiki-effects",
        "psychonautwiki-experiences", "rxnorm-drugs", "ocp-media-intents",
        "prog-archives",
    }
    return n in in_scope_names


def _load_ckpt() -> dict:
    if CKPT_PATH.exists():
        try:
            return json.loads(CKPT_PATH.read_text())
        except Exception:
            pass
    return {"moved": [], "added_to_collection": []}


def _save_ckpt(ckpt: dict) -> None:
    CKPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CKPT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(ckpt, indent=2))
    tmp.rename(CKPT_PATH)


def migrate(dry_run: bool, token: Optional[str]) -> None:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    ckpt = _load_ckpt()
    moved: set = set(ckpt["moved"])
    added: set = set(ckpt["added_to_collection"])
    errors: List[str] = []

    # ── Discover LeData collection slugs ────────────────────────────────────
    print("Fetching LeData collection slugs …")
    ledata_cols = {c.title.lower(): c.slug for c in api.list_collections(owner=TARGET_NS)}
    print(f"  Found {len(ledata_cols)} LeData collections: {list(ledata_cols.keys())}")

    COL_SLUG: Dict[str, Optional[str]] = {
        "drugs": next((s for t, s in ledata_cols.items() if "drug" in t or "substance" in t), None),
        "adult": next((s for t, s in ledata_cols.items() if "adult" in t), None),
        "anime": next((s for t, s in ledata_cols.items() if "anime" in t or "manga" in t), None),
        "romhacks": next((s for t, s in ledata_cols.items() if "rom" in t), None),
        "games": next((s for t, s in ledata_cols.items() if "game" in t), None),
        "books": next((s for t, s in ledata_cols.items() if "book" in t or "podcast" in t), None),
        "imdb": next((s for t, s in ledata_cols.items() if "imdb" in t), None),
        "movie": next((s for t, s in ledata_cols.items() if "movie" in t), None),
        "music": next((s for t, s in ledata_cols.items() if "music" in t), None),
        "media": next((s for t, s in ledata_cols.items() if "media metadata" in t), None),
    }
    print("  Collection slug mapping:")
    for k, v in COL_SLUG.items():
        print(f"    {k:10s} → {v}")

    # ── Find all remaining TigreGotico datasets in scope ────────────────────
    print(f"\nFetching all {SOURCE_NS} datasets …")
    all_src = list(api.list_datasets(author=SOURCE_NS))
    in_scope = [d for d in all_src if _is_in_scope(d.id)]
    already_at_ledata = {d.id.removeprefix(f"{SOURCE_NS}/") for d in api.list_datasets(author=TARGET_NS)}

    print(f"  Total {SOURCE_NS} datasets: {len(all_src)}")
    print(f"  In migration scope: {len(in_scope)}")

    to_move = [d for d in in_scope
               if d.id.removeprefix(f"{SOURCE_NS}/") not in already_at_ledata
               and f"{TARGET_NS}/{d.id.removeprefix(SOURCE_NS+'/')}" not in moved]
    already_there = [d for d in in_scope
                     if d.id.removeprefix(f"{SOURCE_NS}/") in already_at_ledata]
    print(f"  Already at LeData: {len(already_there)}")
    print(f"  Need to move: {len(to_move)}")

    if to_move:
        print("\nRepos to move:")
        for d in to_move:
            print(f"  {d.id}")

    # ── Move each remaining repo ─────────────────────────────────────────────
    for d in to_move:
        src_id = d.id
        dst_id = f"{TARGET_NS}/{src_id.removeprefix(SOURCE_NS + '/')}"
        print(f"\nMOVE {src_id} → {dst_id}")
        if not dry_run:
            try:
                api.move_repo(from_id=src_id, to_id=dst_id, repo_type="dataset")
                moved.add(dst_id)
                ckpt["moved"] = list(moved)
                _save_ckpt(ckpt)
                time.sleep(0.5)
                print(f"  OK")
            except Exception as exc:
                print(f"  ERROR: {exc}")
                errors.append(f"move:{src_id}: {exc}")

    # ── Add all in-scope LeData repos to their collections ──────────────────
    print("\nAdding all in-scope LeData repos to collections …")
    all_dst = (
        [f"{TARGET_NS}/{d.id.removeprefix(SOURCE_NS+'/')}" for d in in_scope]
        + [dst for dst in moved]
    )
    seen_dst = set()
    for dst_id in all_dst:
        if dst_id in seen_dst:
            continue
        seen_dst.add(dst_id)

        repo_name = dst_id.removeprefix(f"{TARGET_NS}/")
        col_key = _classify(repo_name)
        col_slug = COL_SLUG.get(col_key)

        add_key = f"{dst_id}::{col_slug}"
        if add_key in added:
            print(f"  SKIP (already added): {dst_id} → {col_key}")
            continue

        if not col_slug:
            print(f"  NO COLLECTION for {col_key} — skipping {dst_id}")
            continue

        print(f"  ADD {dst_id} [{col_key}] → {col_slug}")
        if not dry_run:
            try:
                api.add_collection_item(
                    collection_slug=col_slug,
                    item_id=dst_id,
                    item_type="dataset",
                    exists_ok=True,
                )
                added.add(add_key)
                ckpt["added_to_collection"] = list(added)
                _save_ckpt(ckpt)
                time.sleep(0.3)
            except Exception as exc:
                print(f"    ERROR: {exc}")
                errors.append(f"add:{dst_id}: {exc}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"  Newly moved: {len(moved)}")
    print(f"  Collection items added: {len(added)}")
    if errors:
        print(f"  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    {e}")
    else:
        print("  No errors.")
    if dry_run:
        print("\n[DRY RUN — nothing changed]")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--token", default=os.environ.get("HF_TOKEN"))
    args = ap.parse_args()
    if not args.token and not args.dry_run:
        from huggingface_hub import HfFolder
        args.token = HfFolder.get_token()
    migrate(dry_run=args.dry_run, token=args.token)


if __name__ == "__main__":
    main()
