"""Open Library book crawler.

Harvests the Open Library ``/search.json`` endpoint across 60+ subject seeds,
deduplicating by OLID. Captures authors, ISBNs, publishers, subjects, page
counts, languages, and ebook availability.

Run it::

    python -m metadatarr.scrapers openlibrary_books [--output DIR] [--limit N] [--delay SECS]
    python -m metadatarr.scrapers.openlibrary_books  # equivalent
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from metadatarr.scrapers.engine import PartitionedJSONSource, register, run_cli

SUBJECTS = [
    "fiction", "non-fiction", "science fiction", "fantasy", "mystery",
    "thriller", "horror", "romance", "biography", "autobiography",
    "history", "science", "philosophy", "psychology", "religion",
    "politics", "economics", "sociology", "anthropology", "archaeology",
    "mathematics", "physics", "chemistry", "biology", "medicine",
    "technology", "computers", "art", "music", "film",
    "photography", "architecture", "cooking", "travel", "sports",
    "children", "young adult", "poetry", "drama", "short stories",
    "essays", "literary criticism", "graphic novels", "comics",
    "manga", "audiobooks", "self-help", "business", "law",
    "education", "language", "linguistics", "folklore", "mythology",
    "occult", "paranormal", "true crime", "nature", "environment",
    "animals", "gardening", "crafts", "humor", "satire",
]


@register
class OpenLibraryBooks(PartitionedJSONSource):
    name = "openlibrary_books"
    id_field = "olid"
    default_delay = 1.0

    base = "https://openlibrary.org/search.json"
    results_key = "docs"
    page_size = 100
    skip_param = "offset"
    limit_param = "limit"
    extra_params = {"fields": "*"}

    def partitions(self) -> List[Dict[str, Any]]:
        return [{"subject": s} for s in SUBJECTS]

    def map_row(self, d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        keys = d.get("key") or ""
        olid = keys.replace("/works/", "").strip() if keys else None
        if not olid:
            return None
        return {
            "olid": olid,
            "title": d.get("title"),
            "subtitle": d.get("subtitle"),
            "authors": d.get("author_name") or [],
            "author_key": d.get("author_key") or [],
            "first_publish_year": d.get("first_publish_year"),
            "subjects": (d.get("subject") or [])[:30],
            "isbn_10": (d.get("isbn") or [])[:5],
            "isbn_13": [],
            "publisher": (d.get("publisher") or [])[:5],
            "language": (d.get("language") or [])[:10],
            "number_of_pages_median": d.get("number_of_pages_median"),
            "ebook_access": d.get("ebook_access"),
            "has_fulltext": d.get("has_fulltext", False),
            "edition_count": d.get("edition_count"),
            "cover_i": d.get("cover_i"),
        }


if __name__ == "__main__":
    raise SystemExit(run_cli(OpenLibraryBooks))
