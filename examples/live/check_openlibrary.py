"""Live check: OpenLibrary — books by ISBN / title."""
from __future__ import annotations

from _common import fail, first_match, pass_
from mediavocab import MediaType
from metadatarr.resolve import Signals, search


def main() -> int:
    cands = search(Signals(title="The Hobbit", artist="J.R.R. Tolkien",
                           medium=MediaType.BOOK))
    m = first_match(cands, "openlibrary")
    if m is None:
        return fail(f"openlibrary returned no match (got {[c.provider for c in cands]})")
    olid = m.external_ids.olid
    isbn = m.external_ids.isbn_13 or m.external_ids.isbn_10
    if not olid and not isbn:
        return fail(f"openlibrary match has no olid or isbn: {m.external_ids}")
    return pass_(f"olid={olid} isbn={isbn}")


if __name__ == "__main__":
    raise SystemExit(main())
