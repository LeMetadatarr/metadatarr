"""Live check: Apple Podcasts (iTunes search) — podcasts."""
from __future__ import annotations

from _common import fail, first_match, pass_
from mediavocab import MediaType
from metadatarr.resolve import Signals, search


def main() -> int:
    cands = search(Signals(title="Reply All", medium=MediaType.PODCAST))
    m = first_match(cands, "apple_podcasts")
    if m is None:
        return fail(f"apple_podcasts returned no match (got {[c.provider for c in cands]})")
    if not m.external_ids.apple_podcast_id:
        return fail(f"apple_podcasts match has no apple_podcast_id: {m.external_ids}")
    return pass_(f"apple_podcast_id={m.external_ids.apple_podcast_id}")


if __name__ == "__main__":
    raise SystemExit(main())
