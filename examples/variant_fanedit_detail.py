"""Fetch full fanedit detail after collecting variant ids from resolve().

User story: "resolve() gave me a list of fanedits with their IFDB ids. Now I
want to fetch the full detail page for each — synopsis, cuts & additions,
runtime, faneditor name, ratings — to help the user pick which edit to watch."

Flow:
  1. resolve() with include_variants=True → result.variants
  2. Filter to entries that have fanedit_id set
  3. Fetch FaneditDetail for each via FaneditClient.get_detail()
"""
import metadatarr.resolve.providers  # trigger self-registration
from pyfanedit import FaneditClient
from metadatarr.resolve import resolve
from mediavocab import MediaType
from mediavocab.models.signals import Signals


def main() -> None:
    client = FaneditClient()

    print("=== Step 1: resolve + collect variant ids ===")
    result = resolve(Signals(
        title="The Phantom Menace",
        year=1999,
        medium=MediaType.MOVIE,
        include_variants=True,
    ))

    releases = result.variants
    with_ids = [r for r in releases if r.external_ids.fanedit_id]
    print(f"  total variants : {len(releases)}")
    print(f"  have fanedit_id: {len(with_ids)}")

    if not with_ids:
        print("  no IFDB ids found — check network connectivity")
        return

    print("\n=== Step 2: fetch full detail for first 3 results ===")
    for variant in with_ids[:3]:
        fid = variant.external_ids.fanedit_id
        print(f"\n  --- {variant.name!r} (fanedit_id={fid}) ---")

        # FaneditClient.get_detail() accepts the IFDB URL.
        # We reconstruct the URL from the fanedit_id via the WordPress ?p= form.
        url = f"https://fanedit.org/?p={fid}"
        try:
            detail = client.get_detail(url)
        except Exception as e:
            print(f"    fetch failed: {e}")
            continue

        print(f"    faneditor       : {detail.faneditor}")
        print(f"    fanedit_type    : {detail.fanedit_type}")
        print(f"    original_title  : {detail.original_title}")
        print(f"    running_time    : {detail.fanedit_running_time}")
        print(f"    editor_rating   : {detail.editor_rating}")
        print(f"    user_rating     : {detail.user_rating} ({detail.user_rating_count} votes)")
        if detail.cuts_and_additions:
            preview = detail.cuts_and_additions[:200].replace("\n", " ")
            print(f"    cuts_preview    : {preview}…")


if __name__ == "__main__":
    main()
