"""Live check: TVmaze — episodic series metadata."""
from __future__ import annotations

from _common import fail, first_match, pass_
from mediavocab import MediaType
from metadatarr.resolve import Signals, search


def main() -> int:
    cands = search(Signals(title="Game of Thrones",
                           medium=MediaType.EPISODIC_SERIES))
    m = first_match(cands, "tvmaze")
    if m is None:
        return fail(f"tvmaze returned no match (got {[c.provider for c in cands]})")
    extra = (m.external_ids.extra or {})
    if not (m.external_ids.imdb or m.external_ids.tvdb or extra):
        return fail(f"tvmaze match has no usable id: {m.external_ids}")
    return pass_(f"imdb={m.external_ids.imdb} tvdb={m.external_ids.tvdb} extra={extra}")


if __name__ == "__main__":
    raise SystemExit(main())
