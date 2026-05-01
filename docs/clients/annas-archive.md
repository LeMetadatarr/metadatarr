# AnnasArchiveClient

Searches [Anna's Archive](https://annas-archive.org/) by scraping the HTML
search results page across a rotating list of mirrors. Unlike the other
clients in metadatarr, this one does **not** call a JSON API — Anna's Archive
does not publish one — and so the failure modes are different.

```python
from metadatarr import AnnasArchiveClient
aa = AnnasArchiveClient()
books = aa.search("Project Hail Mary")
```

## What it does

1. Iterates `self.mirrors` in order.
2. For each, fetches `{mirror}/search?q={query}&display=table`.
3. On the first 2xx response, parses the HTML table with BeautifulSoup.
4. Stores the working mirror on `self.working_mirror` for subsequent calls
   (no auto-rotation between calls — see [Caveats](#caveats)).
5. Returns `list[AnnasArchiveBook]`.

If every mirror fails or returns non-2xx, `search` returns `[]`.

## Default mirror list

```python
AnnasArchiveClient.DEFAULT_MIRRORS = [
    "https://annas-archive.se",
    "https://annas-archive.li",
    "https://annas-archive.pm",
    "https://annas-archive.in",
    "https://annas-archive.gl",
    "https://annas-archive.pk",
    "https://annas-archive.vg",
    "https://annas-archive.gd",
]
```

These TLDs change over time (domain seizures, blocking, new mirrors). If the
defaults stop working, override:

```python
aa = AnnasArchiveClient(mirrors=[
    "https://my-known-good-mirror.example",
    *AnnasArchiveClient.DEFAULT_MIRRORS,
])
```

## The `AnnasArchiveBook` model

| Field | Type | Notes |
|---|---|---|
| `title` | `str` | As displayed in the search table |
| `author` | `str` | Comma-separated authors, raw |
| `formats` | `Optional[str]` | Uppercase, e.g. `"PDF"`, `"EPUB"`. Sometimes a comma list |
| `md5` | `str` | The unique MD5 hash — stable across mirrors |
| `cover_url` | `Optional[str]` | Often a relative URL on the mirror |
| `language` | `Optional[str]` | Two-letter or full name, depends on Anna's input |
| `size` | `Optional[str]` | Human readable, e.g. `"3.4 MB"` |

The `md5` is the durable identifier. To open a result page on whatever mirror
is currently up:

```python
book = books[0]
url = f"{aa.working_mirror}/md5/{book.md5}"
```

## Choosing a working mirror up front

If you call `search` many times you can warm up the working mirror with one
cheap request:

```python
aa = AnnasArchiveClient()
aa.search("a")  # first call probes mirrors; sets aa.working_mirror
print("using:", aa.working_mirror)
```

Subsequent calls **still iterate from the top of `aa.mirrors`** — there's no
sticky-mirror logic. If you want sticky behaviour:

```python
class StickyAnnas(AnnasArchiveClient):
    def search(self, query, timeout=15):
        if self.working_mirror:
            self.mirrors = [self.working_mirror] + [m for m in self.mirrors if m != self.working_mirror]
        return super().search(query, timeout=timeout)
```

## Caveats

- **HTML scraping is fragile.** Anna's Archive ships UI changes periodically.
  If `_parse_search_results` returns `[]` while the website clearly has
  results, the table column order has changed. The current parser expects
  ≥10 columns with: `[cover, title, author, language, ?, ?, ?, ?, size, formats, …]`.
- **Mirror availability varies by region.** A mirror that resolves from the
  US may be DNS-blocked from another country and vice versa.
- **No rate limit awareness.** Hammer at your peril.
- **Legal context.** Anna's Archive aggregates shadow library content. Use
  responsibly and in compliance with your local law.
