"""Live check: Jikan (MyAnimeList proxy) — anime + manga via genre routing."""
from __future__ import annotations

from _common import fail, first_match, pass_
from mediavocab import MediaType
from metadatarr.resolve import Signals, search


def main() -> int:
    # Anime
    cands = search(Signals(title="Cowboy Bebop", medium=MediaType.EPISODIC_SERIES,
                           content_genres=["anime"]))
    a = first_match(cands, "jikan_anime")
    if a is None or not a.external_ids.mal_id:
        return fail(f"jikan_anime did not return a mal_id (cands: {[c.provider for c in cands]})")
    # Manga
    cands = search(Signals(title="Berserk", medium=MediaType.COMIC,
                           content_genres=["manga"]))
    m = first_match(cands, "jikan_manga")
    if m is None or not m.external_ids.mal_id:
        return fail(f"jikan_manga did not return a mal_id (cands: {[c.provider for c in cands]})")
    return pass_(f"jikan_anime mal_id={a.external_ids.mal_id} jikan_manga mal_id={m.external_ids.mal_id}")


if __name__ == "__main__":
    raise SystemExit(main())
