# Getting started

This page takes you from "never used metadatarr" to "successfully enriched a piece
of media metadata." About 5 minutes if you read; 30 seconds if you skim.

## Install

```bash
pip install .
```

From a checkout of this repo. There's no PyPI release yet. Dependencies are
`requests`, `pydantic>=2`, and `beautifulsoup4` (only needed if you use
`AnnasArchiveClient`).

Python 3.9+ is required (Pydantic V2 baseline).

## Your first call (30 seconds)

```python
from metadatarr import ArrMetadataClient

client = ArrMetadataClient()
results = client.search_series("The Expanse")

for show in results[:3]:
    print(show.tvdb_id, show.title, show.year)
```

That call hits `https://skyhook.sonarr.tv/v1/tvdb/search/en/?term=The+Expanse`,
parses the JSON list, and validates each entry into a `SonarrSeries` model.

If anything goes wrong — DNS, 500, JSON parse error, schema mismatch — you get
`[]` back, not an exception. See [Failure modes](#failure-modes) below.

## The mental model

There are **nine** independent client classes. They share nothing except the
`metadatarr` namespace and the convention of returning Pydantic models:

```text
metadatarr
├── ArrMetadataClient    → Sonarr / Radarr / Lidarr metadata proxies
├── BookInfoClient       → rreading-glasses (Goodreads or Hardcover)
├── OpenLibraryClient    → OpenLibrary REST API
├── AnnasArchiveClient   → Anna's Archive HTML scraping (mirror rotation)
├── AudioDBClient        → TheAudioDB artist / album / track
├── TVmazeClient         → TVmaze TV show / season / cast
│
│   Physical disc (import from metadatarr.client, not the top-level package)
├── BlurayComClient      → blu-ray.com technical specs (HTML scraper)
├── DVDCompareClient     → dvdcompare.net cut / version metadata (HTML scraper)
└── DiscogsClient        → Discogs label, catalogue number, VHS, LaserDisc (REST API)
```

Plus a separate **resolve** subpackage (`metadatarr.resolve`) that fuses
matches from many providers into one record — see
[resolve.md](resolve.md).

Pick the client by **what you have** and **what you want**:

| You have… | You want… | Use |
|---|---|---|
| A show name | TVDB ID, year, overview | `ArrMetadataClient.search_series` |
| A movie name | TMDB ID, year, overview | `ArrMetadataClient.search_movie` |
| An artist name | MusicBrainz ID, bio | `ArrMetadataClient.search_artist` |
| A book/author name + Goodreads-style data | work/edition/author triplet | `BookInfoClient.goodreads()` |
| A book/author name + Hardcover data | work/edition/author triplet | `BookInfoClient.hardcover()` |
| An ISBN | publisher, page count, cover | `OpenLibraryClient.get_edition_by_isbn` |
| A book title and need to find downloadable copies | mirror-hosted file refs | `AnnasArchiveClient.search` |
| A disc title | technical specs (codec, HDR, bitrate, audio) | `BlurayComClient.search` + `get_edition` |
| A disc title | Director's Cut vs Theatrical, version differences | `DVDCompareClient.search` + `get_edition` |
| A disc title or format (VHS, LaserDisc) | label, catalogue number, country | `DiscogsClient.search_film` + `get_release` |

## A slightly bigger example

Enrich a movie title with both TMDB metadata (via Radarr) and a downloadable
copy reference (via Anna's Archive — yes, books, but the pattern generalises):

```python
from metadatarr import ArrMetadataClient, BookInfoClient, OpenLibraryClient

arr = ArrMetadataClient()
bookinfo = BookInfoClient.goodreads()
ol = OpenLibraryClient()

# Movies → TMDB
movies = arr.search_movie("Dune")
print(movies[0].title, movies[0].tmdb_id)

# Books → Goodreads (via rreading-glasses)
hits = bookinfo.search("Dune Frank Herbert")
work = bookinfo.get_work(hits[0].work_id)
print(work.title, len(work.books), "editions")

# Books → OpenLibrary
ol_hits = ol.search("Dune Frank Herbert", limit=1)
print(ol_hits[0].work_id, ol_hits[0].first_publish_year)
```

## Failure modes

metadatarr's design rule: **a provider being down or returning garbage must not
crash your pipeline.** Every method that returns a list will return `[]` on
failure, every method that returns a single record will return `None`.

What this means in practice:

```python
results = client.search_series("nonsense")  # always a list, possibly empty
if not results:
    ...  # provider down OR no matches — same shape

show = client.get_series_info(999_999_999)  # None on miss, None on error
if show is None:
    ...
```

If you need to *distinguish* "no result" from "provider exploded", you have two
options:

1. Subclass and override `_get` to raise instead of swallow.
2. Use the lower-level methods directly — `requests.get(...)` is one layer down.

There is no built-in retry, no built-in caching, no rate limiter. These belong
in your pipeline, not in a metadata client. See [Recipes](recipes.md) for
patterns.

## Running the tests

The suite is fully offline (HTTP is patched), so it runs anywhere with no keys
and no network:

```bash
pip install .[test]
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` matches CI (it stops third-party pytest
plugins from loading). The same command runs on every PR via the shared
`gh-automations` workflows, alongside coverage, lint, license check, and
pip-audit. See [testing.md](testing.md) for how provider tests are written and
[../CONTRIBUTING.md](../CONTRIBUTING.md) for the branch/commit/versioning flow.

## Where to go next

- **[Models reference](models.md)** — every field on every model, with origin annotations.
- **One of the per-client guides** linked from the [docs index](README.md).
- **[Recipes](recipes.md)** — concrete cross-provider workflows.
- **[Adding a provider](add-provider.md)** — extend the resolver with a new source.
- **[Testing providers](testing.md)** — the offline-fixture / mocked-HTTP pattern.
