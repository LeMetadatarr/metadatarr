"""Live check: Google Books — books / audiobooks."""
from __future__ import annotations

from _common import fail, first_match, pass_
from mediavocab import MediaType
from metadatarr.resolve import Signals, search


def main() -> int:
    # Probe upstream directly — Google Books rate-limits anonymous calls
    # to ~1000/day; treat 429 as SKIP, not FAIL.
    import httpx
    from _common import skip
    try:
        r = httpx.get("https://www.googleapis.com/books/v1/volumes",
                      params={"q": "intitle:Dune", "maxResults": 1}, timeout=10)
        if r.status_code == 429:
            return skip(f"google_books rate-limited (HTTP 429)")
        r.raise_for_status()
    except httpx.HTTPError as exc:
        return skip(f"google_books unreachable: {exc}")

    cands = search(Signals(title="Dune", artist="Frank Herbert",
                           medium=MediaType.BOOK))
    m = first_match(cands, "google_books")
    if m is None:
        return fail(f"google_books returned no match (got {[c.provider for c in cands]})")
    gid = m.external_ids.google_books_id
    isbn = m.external_ids.isbn_13 or m.external_ids.isbn_10
    if not gid:
        return fail(f"google_books match has no google_books_id: {m.external_ids}")
    return pass_(f"google_books_id={gid} isbn={isbn}")


if __name__ == "__main__":
    raise SystemExit(main())
