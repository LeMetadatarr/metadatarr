"""Live check: AniList GraphQL — anime via genre-axis routing.

Anime is genre, not media type (axiom 2). Routing is
``MediaType.EPISODIC_SERIES`` + ``content_genres=["anime"]``.
"""
from __future__ import annotations

from _common import fail, first_match, pass_
from mediavocab import MediaType
from metadatarr.resolve import Signals, search


def main() -> int:
    sig = Signals(title="Cowboy Bebop", medium=MediaType.EPISODIC_SERIES,
                  content_genres=["anime"])
    cands = search(sig)
    m = first_match(cands, "anilist")
    if m is None:
        return fail(f"anilist returned no match (got {[c.provider for c in cands]})")
    aid = m.external_ids.anilist_id or m.external_ids.anilist_anime_id
    if not aid:
        return fail(f"anilist match has no anilist id: {m.external_ids}")
    return pass_(f"anilist confidence={m.confidence:.2f} anilist_id={aid}")


if __name__ == "__main__":
    raise SystemExit(main())
