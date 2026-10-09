# Troubleshooting

Things that commonly break, with diagnoses and fixes.

## "A provider returns nothing"

Before guessing why, check `result.provider_errors`. When a provider raises
during `resolve()`, the failure is swallowed to keep the run going, but it is
recorded there as a `ProviderError` (`provider`, `stage`, `error_type`,
`message`):

```python
result = resolve(Signals(title="Dune", medium=MediaType.BOOK))
for err in result.provider_errors:
    print(err.provider, err.stage, err.error_type, err.message)
```

An empty `provider_errors` means every provider ran cleanly and genuinely had no
match; a populated one points straight at the provider and stage that broke —
usually upstream schema drift. See
[`provider_errors`](resolve.md#provider-errors--resultprovider_errors) for the
field reference. The same failures are logged under the `metadatarr.resolve`
logger.

## "I get an empty list / `None` for everything"

metadatarr [swallows all errors](getting-started.md#failure-modes) by design, so an
empty list can mean any of:

1. **Genuine no-match.** Search the same term in the upstream's web UI:
   - Sonarr: <https://skyhook.sonarr.tv/v1/tvdb/search/en/?term=...>
   - Radarr: <https://radarrapi.servarr.com/v1/search?q=...>
   - OpenLibrary: <https://openlibrary.org/search?q=...>
2. **Provider down.** Same URLs as above: if the browser shows 502/timeout,
   the provider is the problem.
3. **Schema drift.** The provider changed its JSON shape and Pydantic
   validation is failing silently. Bypass metadatarr to confirm:

   ```python
   import requests
   r = requests.get("https://api.bookinfo.pro/search", params={"q": "dune"}, timeout=10)
   print(r.status_code)
   print(r.json()[:2])
   ```

   If the JSON looks different from what the model expects, file an issue or
   patch `models.py`.

To get loud errors during debugging, monkey-patch `_get`:

```python
client = OpenLibraryClient()
_orig = client._get

def loud(path, params=None):
    import requests
    r = requests.get(f"{client.base_url}{path}", headers=client.headers,
                     params=params, timeout=client.timeout)
    r.raise_for_status()
    return r.json()

client._get = loud
```

## "Anna's Archive returns nothing but the website works"

Three possibilities:

1. **All default mirrors are blocked from your network.** Try one in a
   browser, if it loads but metadatarr returns `[]`, your DNS / VPN setup is
   different from your Python process.
2. **The HTML structure changed.** `_parse_search_results` expects a
   `<table>` with rows of ≥10 columns. Pull a sample page and inspect:

   ```python
   import requests
   html = requests.get("https://annas-archive.se/search?q=dune&display=table").text
   open("/tmp/aa.html", "w").write(html)
   ```

   If column count or order changed, the parser needs updating.
3. **Cloudflare challenge.** Anna's mirrors sometimes serve a JS challenge
   page to non-browser UAs. Pass a real-browser `User-Agent` and consider
   using `cloudscraper` or a session with cookies.

## "Lidarr/Skyhook returns 500 on a name that should exist"

Servarr proxies are public, unauthenticated, and occasionally unreliable: especially MusicInfo. Retry once after a few seconds. If it persists, the
proxy is having an outage, nothing you can do client-side.

## "OpenLibrary cover URL returns a 1×1 transparent PNG"

OpenLibrary's covers service serves a 1px placeholder for missing covers
**with HTTP 200**. To force a 404 instead so you can fall back, append
`?default=false`:

```python
url = OpenLibraryClient.cover_url(cover_id) + "?default=false"
```

A `404` will then mean "no cover for this ID" so your fallback logic can
chain to another source.

## "BookInfoClient `get_book` returns None for a real book ID"

This is normal. `rreading-glasses` may not have the per-edition record cached
even when `/work/{work_id}` knows about that edition. Use the work's `books`
list instead:

```python
work = client.get_work(hit.work_id)
edition = next((b for b in work.books if b.foreign_id == hit.book_id), None)
```

## "Hardcover and Goodreads results conflict"

They will. Different ID spaces, different curation. Don't try to map IDs
between them: match on `(title, author, publication_year)` if you must
deduplicate. See [Recipes → Dedup](recipes.md#dedup-search-results-across-two-book-backends).

## "Pydantic validation error on a field that's clearly in the response"

Two common causes:

1. **Casing.** The model uses `AliasChoices` to accept multiple casings,
   but if upstream invents a *new* casing it'll break. Add it:

   ```python
   field_name: int = Field(validation_alias=AliasChoices("foo", "Foo", "FOO_NEW"))
   ```

2. **Type drift.** Upstream switched a field from `int` to `str` (or wrapped
   it in `{value: ...}`). Use `Optional[Union[...]]` and a validator, or
   override the model's parsing as `OpenLibraryWork.from_api` does for the
   `description` field.

## "I can't tell if I'm being rate-limited"

None of the providers return clear `429`s consistently. Symptoms of
rate-limiting:

- Suddenly all results are `[]` from one provider only.
- Increased latency followed by timeouts.
- Inconsistent results for the same query.

Mitigation: a `requests_cache.CachedSession` (see
[Recipes → Caching & sessions](recipes.md#caching--sessions)) usually solves
this for free during development. In production, add explicit sleeps or use
a token bucket if you're doing >1 req/sec sustained.

## "I need to debug what URL metadatarr is actually hitting"

Drop in a `Session` with logging:

```python
import logging, http.client
http.client.HTTPConnection.debuglevel = 1
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.DEBUG)

from metadatarr import OpenLibraryClient
OpenLibraryClient().search("dune")
```

You'll see every HTTP request line and response status on stderr.

---
[← Recipes](recipes.md) · [Home](README.md) · [Adding a provider →](add-provider.md)
