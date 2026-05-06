"""Live check: LibriVox — public-domain audiobooks."""
from __future__ import annotations

from _common import fail, first_match, pass_
from mediavocab import MediaType
from metadatarr.resolve import Signals, search


def main() -> int:
    cands = search(Signals(title="Pride and Prejudice", artist="Jane Austen",
                           medium=MediaType.AUDIOBOOK))
    m = first_match(cands, "librivox")
    if m is None:
        return fail(f"librivox returned no match (got {[c.provider for c in cands]})")
    if not m.external_ids.librivox_id:
        return fail(f"librivox match has no librivox_id: {m.external_ids}")
    return pass_(f"librivox_id={m.external_ids.librivox_id}")


if __name__ == "__main__":
    raise SystemExit(main())
