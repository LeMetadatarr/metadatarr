"""Migrate HuggingFace collections from TigreGotico → LeData.

For each target collection:
  1. Fetch all items from the source collection.
  2. Move each dataset repo TigreGotico/<name> → LeData/<name> via move_repo().
  3. Create an equivalent collection under LeData.
  4. Add all moved repos to the new collection.
  5. Verify every item is accessible under LeData.
  6. Delete the original TigreGotico collection.

The script is fully resumable: a JSON checkpoint records which repos have been
moved, which collections have been created, and which source collections have
been deleted.

Usage:
    python migrate_hf_collections.py [--dry-run] [--token TOKEN] [--skip-delete]

    --dry-run      Plan + validate without moving/deleting anything
    --skip-delete  Move and recreate but leave source collections intact
    --token        HF token (default: HF_TOKEN env or huggingface-cli login)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Target collections to migrate (source slug → target namespace/title)
# ---------------------------------------------------------------------------

COLLECTIONS = [
    "TigreGotico/drugs-and-substances-6a1e0c07447ed909ef9731c4",
    "TigreGotico/media-metadata-6a1e0d757bb2d85de80b4eb8",
    "TigreGotico/adult-metadata-6a400718a07b5c23d8f424df",
    "TigreGotico/books-and-podcasts-6a400b1882dee5fe379442d8",
    "TigreGotico/music-metadata-6a4008197b67589b85ed3297",
    "TigreGotico/imdb-metadata-6a400658b1d98b18fbfa5035",
    "TigreGotico/games-metadata-6a400b198fbfc742ff867d58",
    "TigreGotico/rom-hacks-metadata-6a400b10a07b5c23d8f4a0b8",
    "TigreGotico/anime-and-manga-metadata-6a400b12fb87315cc98e1b6a",
    "TigreGotico/movie-metadata-6a400b171ba1a6894501d202",
]

TARGET_NS = "LeData"
SOURCE_NS = "TigreGotico"

CKPT_PATH = Path.home() / ".cache" / "metadatarr" / "migrate_hf_checkpoint.json"


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def _load_ckpt() -> Dict[str, Any]:
    if CKPT_PATH.exists():
        try:
            return json.loads(CKPT_PATH.read_text())
        except Exception:
            pass
    return {"moved_repos": [], "created_collections": {}, "deleted_collections": []}


def _save_ckpt(ckpt: Dict[str, Any]) -> None:
    CKPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CKPT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(ckpt, indent=2))
    tmp.rename(CKPT_PATH)


# ---------------------------------------------------------------------------
# Main migration logic
# ---------------------------------------------------------------------------

def migrate(dry_run: bool, skip_delete: bool, token: Optional[str]) -> None:
    from huggingface_hub import HfApi
    from huggingface_hub.utils import RepositoryNotFoundError

    api = HfApi(token=token)
    ckpt = _load_ckpt()
    moved_repos: set = set(ckpt["moved_repos"])
    created_collections: Dict[str, str] = ckpt["created_collections"]  # src_slug → new_slug
    deleted_collections: set = set(ckpt["deleted_collections"])

    errors: List[str] = []

    for src_slug in COLLECTIONS:
        print(f"\n{'='*70}")
        print(f"COLLECTION: {src_slug}")
        print(f"{'='*70}")

        # ── 1. Fetch source collection ──────────────────────────────────────
        try:
            col = api.get_collection(src_slug)
        except Exception as exc:
            print(f"  ERROR fetching collection: {exc}")
            errors.append(f"fetch:{src_slug}: {exc}")
            continue

        title = col.title
        description = col.description or ""
        private = col.private
        items = col.items
        print(f"  title={title!r}  items={len(items)}  private={private}")

        # ── 2. Move each repo ───────────────────────────────────────────────
        target_item_ids: List[tuple] = []  # (new_item_id, item_type)

        for item in items:
            src_id = item.item_id
            itype = item.item_type  # 'dataset', 'model', 'space'

            # Only move repos owned by SOURCE_NS; leave foreign items as-is
            if src_id.startswith(f"{SOURCE_NS}/"):
                repo_name = src_id.split("/", 1)[1]
                dst_id = f"{TARGET_NS}/{repo_name}"
            else:
                print(f"  SKIP (external): {src_id}")
                target_item_ids.append((src_id, itype))
                continue

            if dst_id in moved_repos:
                print(f"  SKIP (already moved): {src_id} → {dst_id}")
                target_item_ids.append((dst_id, itype))
                continue

            print(f"  MOVE {src_id} → {dst_id} [{itype}]")
            if not dry_run:
                try:
                    api.move_repo(from_id=src_id, to_id=dst_id, repo_type=itype)
                    moved_repos.add(dst_id)
                    ckpt["moved_repos"] = list(moved_repos)
                    _save_ckpt(ckpt)
                    time.sleep(0.5)
                except Exception as exc:
                    print(f"    ERROR moving {src_id}: {exc}")
                    errors.append(f"move:{src_id}: {exc}")
                    # Still add to target list — it may already be there
            target_item_ids.append((dst_id, itype))

        # ── 3. Create collection under TARGET_NS ────────────────────────────
        if src_slug in created_collections:
            new_slug = created_collections[src_slug]
            print(f"  SKIP create (already exists): {new_slug}")
        else:
            print(f"  CREATE collection {TARGET_NS!r} title={title!r}")
            if not dry_run:
                try:
                    new_col = api.create_collection(
                        title=title,
                        namespace=TARGET_NS,
                        description=description,
                        private=private,
                        exists_ok=True,
                    )
                    new_slug = new_col.slug
                    created_collections[src_slug] = new_slug
                    ckpt["created_collections"] = created_collections
                    _save_ckpt(ckpt)
                    print(f"    Created: {new_slug}")
                    time.sleep(0.5)
                except Exception as exc:
                    print(f"    ERROR creating collection: {exc}")
                    errors.append(f"create_collection:{src_slug}: {exc}")
                    new_slug = None
            else:
                new_slug = f"{TARGET_NS}/<new-{title.lower().replace(' ','-')}>"

        # ── 4. Add items to new collection ──────────────────────────────────
        if new_slug and not dry_run:
            for item_id, itype in target_item_ids:
                print(f"  ADD {item_id} [{itype}] → {new_slug}")
                try:
                    api.add_collection_item(
                        collection_slug=new_slug,
                        item_id=item_id,
                        item_type=itype,
                        exists_ok=True,
                    )
                    time.sleep(0.3)
                except Exception as exc:
                    print(f"    ERROR adding {item_id}: {exc}")
                    errors.append(f"add_item:{item_id}→{new_slug}: {exc}")

        # ── 5. Verify ────────────────────────────────────────────────────────
        if new_slug and not dry_run:
            print(f"  VERIFY {new_slug}")
            missing = []
            try:
                new_col_check = api.get_collection(new_slug)
                actual_ids = {it.item_id for it in new_col_check.items}
                for item_id, _ in target_item_ids:
                    if item_id not in actual_ids:
                        missing.append(item_id)
            except Exception as exc:
                print(f"    ERROR verifying: {exc}")
                missing = ["<could not verify>"]

            if missing:
                print(f"    MISSING from new collection: {missing}")
                errors.extend(f"missing:{m}" for m in missing)
            else:
                print(f"    OK — all {len(target_item_ids)} items present in {new_slug}")

        # ── 6. Delete original collection ────────────────────────────────────
        if skip_delete or dry_run:
            print(f"  SKIP delete (--skip-delete or --dry-run): {src_slug}")
        elif src_slug in deleted_collections:
            print(f"  SKIP delete (already done): {src_slug}")
        elif errors:
            print(f"  SKIP delete (errors present — fix first): {src_slug}")
        else:
            print(f"  DELETE original collection: {src_slug}")
            try:
                api.delete_collection(src_slug, missing_ok=True)
                deleted_collections.add(src_slug)
                ckpt["deleted_collections"] = list(deleted_collections)
                _save_ckpt(ckpt)
                print(f"    Deleted: {src_slug}")
                time.sleep(0.5)
            except Exception as exc:
                print(f"    ERROR deleting: {exc}")
                errors.append(f"delete:{src_slug}: {exc}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("MIGRATION SUMMARY")
    print(f"{'='*70}")
    print(f"  Repos moved:           {len(moved_repos)}")
    print(f"  Collections created:   {len(created_collections)}")
    print(f"  Collections deleted:   {len(deleted_collections)}")
    if errors:
        print(f"  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    {e}")
    else:
        print("  No errors.")

    if dry_run:
        print("\n[DRY RUN — nothing was changed]")


def main() -> None:
    ap = argparse.ArgumentParser(description="Migrate HF collections TigreGotico → LeData")
    ap.add_argument("--dry-run", action="store_true",
                    help="Plan without making any changes")
    ap.add_argument("--skip-delete", action="store_true",
                    help="Move/recreate but keep original collections")
    ap.add_argument("--token", default=os.environ.get("HF_TOKEN"),
                    help="HuggingFace token (default: HF_TOKEN env)")
    args = ap.parse_args()

    if not args.token and not args.dry_run:
        # Try huggingface-cli login cache
        from huggingface_hub import HfFolder
        args.token = HfFolder.get_token()
        if not args.token:
            print("ERROR: no HF token found. Set HF_TOKEN or run `huggingface-cli login`.")
            sys.exit(1)

    migrate(dry_run=args.dry_run, skip_delete=args.skip_delete, token=args.token)


if __name__ == "__main__":
    main()
