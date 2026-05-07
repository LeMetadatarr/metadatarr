# Recipes

Cross-provider patterns and copy-pasteable snippets. Everything here uses
**only** what's in metadatarr's stdlib + `requests`/`pydantic` dependencies.

## ISBN → cover, description, page count

Use OpenLibrary as the primary because ISBN lookup is direct and free:

```python
from metadatarr import OpenLibraryClient

ol = OpenLibraryClient()

def enrich_isbn(isbn: str) -> dict:
    edition = ol.get_edition_by_isbn(isbn)
    if not edition:
        return {}

    work = ol.get_work(edition.work_keys[0]) if edition.work_keys else None
    cover = (
        OpenLibraryClient.cover_url(edition.covers[0]) if edition.covers
        else f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"
    )
    return {
        "title": edition.title,
        "subtitle": edition.subtitle,
        "publishers": edition.publishers,
        "pages": edition.number_of_pages,
        "publish_date": edition.publish_date,
        "description": work.description if work else None,
        "subjects": work.subjects if work else [],
        "cover": cover,
    }
```

## Title → best cover (multi-source fallback)

```python
from metadatarr import OpenLibraryClient, BookInfoClient

def best_cover(title: str, author: str | None = None) -> str | None:
    query = f"{title} {author}" if author else title

    ol = OpenLibraryClient()
    for hit in ol.search(query, limit=5):
        if hit.cover_id:
            return OpenLibraryClient.cover_url(hit.cover_id)

    for client in (BookInfoClient.goodreads(), BookInfoClient.hardcover()):
        for hit in client.search(query):
            work = client.get_work(hit.work_id)
            if not work:
                continue
            for ed in work.books:
                if ed.image_url:
                    return ed.image_url
    return None
```

## Provider fallback chain

A generic "first non-empty wins" helper:

```python
from typing import Callable, TypeVar

T = TypeVar("T")

def first_nonempty(*calls: Callable[[], list[T]]) -> list[T]:
    for call in calls:
        result = call()
        if result:
            return result
    return []

# Usage
from metadatarr import BookInfoClient

gr, hc = BookInfoClient.goodreads(), BookInfoClient.hardcover()
hits = first_nonempty(
    lambda: gr.search("The Three-Body Problem"),
    lambda: hc.search("The Three-Body Problem"),
)
```

## Dedup search results across two book backends

`BookInfoClient` Goodreads and Hardcover use disjoint integer ID spaces, so
naive merge produces duplicates. Dedup by `(title.lower(), first_author)`:

```python
from metadatarr import BookInfoClient

def merged_search(query: str):
    seen = set()
    out = []
    for client in (BookInfoClient.goodreads(), BookInfoClient.hardcover()):
        for hit in client.search(query):
            work = client.get_work(hit.work_id)
            if not work or not work.books:
                continue
            key = (work.title.lower().strip(), work.books[0].title or "")
            if key in seen:
                continue
            seen.add(key)
            out.append((client, hit, work))
    return out
```

## Async wrapper

metadatarr is sync. Wrap with `asyncio.to_thread` (Python 3.9+) when you need
to fan out:

```python
import asyncio
from metadatarr import ArrMetadataClient

arr = ArrMetadataClient()

async def search_many(terms: list[str]):
    return await asyncio.gather(*(
        asyncio.to_thread(arr.search_movie, t) for t in terms
    ))

results = asyncio.run(search_many(["Dune", "Arrival", "Annihilation"]))
```

For high-throughput use, pool `requests.Session` instead — see
[Caching & sessions](#caching--sessions) below.

## Caching & sessions

The default client constructs a fresh `requests` call each time. For bulk
work, swap to a `Session` (connection pooling + `requests-cache` for free)
by subclassing:

```python
import requests
import requests_cache
from metadatarr import OpenLibraryClient

class CachedOL(OpenLibraryClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = requests_cache.CachedSession(
            "openlibrary_cache",
            expire_after=3600,  # 1 hour
        )

    def _get(self, path, params=None):
        try:
            r = self.session.get(f"{self.base_url}{path}", headers=self.headers,
                                 params=params, timeout=self.timeout)
            r.raise_for_status()
            return r.json() if r.content else None
        except Exception:
            return None
```

The same pattern works for `BookInfoClient` and `ArrMetadataClient`.

## Retry with backoff

Wrap `_get` with `tenacity`:

```python
from tenacity import retry, stop_after_attempt, wait_exponential
from metadatarr import ArrMetadataClient

class RetryArr(ArrMetadataClient):
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def _get(self, url, params=None):
        return super()._get(url, params=params)
```

> ⚠️ The base `_get` swallows all exceptions and returns `[]` / `{}`. To make
> retry work, you must **raise** on failure — override `_get` from scratch
> rather than wrapping the swallowing version.

## Batch enrichment with progress

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from metadatarr import OpenLibraryClient

ol = OpenLibraryClient()

def enrich_one(isbn: str):
    return isbn, ol.get_edition_by_isbn(isbn)

def enrich_many(isbns: list[str], workers: int = 8):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(enrich_one, i): i for i in isbns}
        for done in as_completed(futures):
            yield done.result()

for isbn, edition in enrich_many(my_isbns):
    print(isbn, "→", edition.title if edition else "MISS")
```

`requests` is thread-safe per-call; eight workers against OpenLibrary is
polite. Don't go higher than ~16 without coordinating with the upstream.

## Pick the best regional Blu-ray edition

Fetch all editions for a title from blu-ray.com, filter to one region, and
rank by HDR type then video bitrate:

```python
from metadatarr.client import BlurayComClient, BlurayComEdition
from typing import List, Optional
import time

_HDR_RANK = {"HDR10+": 3, "Dolby Vision": 2, "HDR10": 1}


def pick_best_edition(title: str, region: str = "B") -> Optional[BlurayComEdition]:
    client = BlurayComClient()
    hits = client.search(title)

    candidates: List[BlurayComEdition] = []
    for hit in hits:
        edition = client.get_edition(hit.bluray_com_id)
        time.sleep(1)
        if edition is None:
            continue
        if edition.region not in (region, "Free"):
            continue
        candidates.append(edition)

    if not candidates:
        return None

    return max(candidates, key=lambda ed: (
        _HDR_RANK.get(ed.hdr or "", 0),
        ed.video_bitrate_kbps or 0,
    ))


best = pick_best_edition("Dune Part Two", region="B")
if best:
    print(best.title, best.hdr, best.video_bitrate_kbps, "kbps")
```

For an explanation of all `BlurayComEdition` fields see
[clients/bluray-com.md](clients/bluray-com.md).

## Resolve Director's Cut vs Theatrical via dvdcompare + resolve system

Use the resolve system with an explicit `VariantKind` to get a consolidated
result where the dvdcompare provider has confirmed the version:

```python
import metadatarr.resolve.providers
from metadatarr.resolve.base import resolve
from mediavocab import Signals, MediaType, VariantKind

def resolve_cut(title: str, cut: VariantKind):
    result = resolve(Signals(
        title=title,
        medium=MediaType.MOVIE,
        variant_kind=cut,
    ))
    version = result.external_ids.extra.get("dvdcompare_version")
    diff = result.external_ids.extra.get("dvdcompare_version_diff")
    return result, version, diff

dc_result, dc_version, dc_diff = resolve_cut(
    "Apocalypse Now", VariantKind.DIRECTORS
)
th_result, th_version, th_diff = resolve_cut(
    "Apocalypse Now", VariantKind.THEATRICAL
)

print("Director's Cut version string:", dc_version)
print("Theatrical version string:", th_version)
print("Differences:", dc_diff)
```

The resolver drops any provider match whose `variant_kind` conflicts with the
one you declared. A provider that doesn't set `variant_kind` (e.g. `bluray_com`
for a standard retail disc) is never dropped — it simply doesn't vote on the
cut. See [resolve.md — VariantKind](resolve.md#variantkind).

## Find a VHS or LaserDisc release on Discogs

Discogs is the only source in metadatarr for these formats:

```python
from metadatarr.client import DiscogsClient
import time

client = DiscogsClient()  # set DISCOGS_TOKEN env var for 60 req/min

def find_physical(title: str, fmt: str):
    """Return full release details for *title* in the given format."""
    hits = client.search(title, fmt=fmt, genre="Non-Music")
    if not hits:
        hits = client.search(title, fmt=fmt)  # unrestricted fallback

    results = []
    for hit in hits[:5]:
        release = client.get_release(hit.id)
        time.sleep(2)  # 25 req/min unauthenticated
        if release:
            results.append(release)
    return results

# VHS
for release in find_physical("Akira", "VHS"):
    print(release.title, release.released, release.country, release.label_names)

# LaserDisc
for release in find_physical("Blade Runner", "Laserdisc"):
    print(release.title, release.released, release.label_names, release.format_names)
```

See [clients/discogs.md](clients/discogs.md) for the full field reference and
rate-limit guidance.

## Voice agent: route by request verb

When a voice assistant parses user intent, the request verb tells you the
modality the user expects. Map it to `PlaybackModality` before resolving —
the three-axis gate does the rest without you enumerating providers manually.

```python
import metadatarr.resolve.providers  # triggers self-registration
from metadatarr.resolve.base import resolve
from mediavocab import Signals, MediaType, PlaybackModality

_VERB_TO_MODALITY = {
    "play":   PlaybackModality.AUDIO,   # "play X" → audio providers
    "listen": PlaybackModality.AUDIO,
    "watch":  PlaybackModality.VIDEO,   # "watch X" → video providers
    "read":   PlaybackModality.TEXT,    # "read X" → text/book providers
}

def resolve_intent(title: str, verb: str, medium: MediaType = MediaType.GENERIC):
    """Resolve *title* using the modality implied by *verb*.

    AUDIO routes to: musicbrainz, audiodb, bandcamp, soundcloud,
                     metal_archives, youtube_music, librivox, apple_podcasts,
                     discogs.
    VIDEO routes to: tvmaze, anilist, jikan_anime, pyfanedit,
                     bluray_com, dvdcompare, skyhook, discogs.
    TEXT routes to:  openlibrary, annas_archive, jikan_manga, anilist.
    """
    modality = _VERB_TO_MODALITY.get(verb.lower())
    return resolve(Signals(title=title, medium=medium, modality=modality))

result = resolve_intent("Moonsorrow", "play")
result = resolve_intent("Attack on Titan", "watch", MediaType.EPISODIC_SERIES)
result = resolve_intent("The Hobbit", "read", MediaType.BOOK)
```

Providers with an empty `modality` set (`skyhook`, `wikidata`, `youtube`) are
universal and participate regardless of the modality passed.
`MetadataProvider.modality` — `metadatarr/resolve/base.py:107`

## Building your own provider class

If you want metadatarr-shaped access to another book/media source, the recipe is:

1. Create a Pydantic model in `models.py` per response shape.
2. Create a client class in `client.py` with a `_get` helper that swallows
   exceptions and returns `[]` / `None`.
3. One method per endpoint, returning validated models.
4. Re-export from `__init__.py`.

That's the entire pattern. See `OpenLibraryClient` for a clean recent example.
