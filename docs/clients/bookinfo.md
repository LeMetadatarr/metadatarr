# BookInfoClient (rreading-glasses)

Wraps [`rreading-glasses`](https://github.com/blampe/rreading-glasses), an
open-source replacement for the defunct Goodreads metadata service.
Two hosted instances exist:

| Backend | URL | Constructor |
|---|---|---|
| Goodreads-derived | `https://api.bookinfo.pro` | `BookInfoClient.goodreads()` |
| Hardcover-derived | `https://hardcover.bookinfo.pro` | `BookInfoClient.hardcover()` |

```python
from metadatarr import BookInfoClient

gr = BookInfoClient.goodreads()
hc = BookInfoClient.hardcover()
```

The two are **API-compatible but content-different**: same endpoints, same
JSON shape, different ID space and different works available. Hardcover has
better newer-book coverage, Goodreads has the long tail of older titles.

## Endpoints

| Method | Returns | Upstream |
|---|---|---|
| `search(query)` | `list[BookInfoSearchHit]` | `GET /search?q=` |
| `get_work(work_id)` | `BookInfoWork \| None` | `GET /work/{id}` |
| `get_book(book_id)` | `BookInfoWork \| None` | `GET /book/{id}` |
| `get_author(author_id)` | `BookInfoAuthor \| None` | `GET /author/{id}` |

> 📝 **Important:** `get_book` returns the parent **work**, not the edition.
> rreading-glasses normalises around works, the edition you asked for will be
> one entry inside `work.books`. This matches Readarr's data model.

## The work / book / author triplet

A `BookInfoSearchHit` is the join row for a result:

```python
hits = gr.search("Three-Body Problem")
hit = hits[0]
hit.book_id    # int: a specific edition (printing) of a work
hit.work_id    # int: the abstract work, all editions share this
hit.author_id  # int | None: the primary author
```

Pivot from there:

```python
work = gr.get_work(hit.work_id)
print(work.title, work.release_date_raw, work.genres)
for edition in work.books:
    print(" -", edition.foreign_id, edition.format, edition.publisher, edition.isbn13)

author = gr.get_author(hit.author_id)
print(author.name, author.description[:120] if author.description else "")
```

## Picking a backend at runtime

The two hosted backends share the abstract layout but **not** the integer IDs.
A `work_id` from `bookinfo.pro` is meaningless on `hardcover.bookinfo.pro` and
vice versa. Don't mix.

If you want to try both and take whichever returns first:

```python
def first_hit(query: str):
    for client in (BookInfoClient.goodreads(), BookInfoClient.hardcover()):
        hits = client.search(query)
        if hits:
            return client, hits[0]
    return None, None
```

See [Recipes → Provider fallback chain](../recipes.md#provider-fallback-chain).

## Self-hosting

`rreading-glasses` is open source. If you run your own instance:

```python
client = BookInfoClient(base_url="https://my-rrg.internal", user_agent="my-app/1.0")
```

The class methods `BookInfoClient.goodreads()` / `BookInfoClient.hardcover()`
are just convenience wrappers around the constructor: there is nothing magic
about the hosted instances.

## Models

See [Models reference → BookInfo*](../models.md#bookinfo) for full field lists.
At a glance:

- `BookInfoWork`: `foreign_id`, `title`, `full_title`, `short_title`, `url`,
  `release_date`, `release_date_raw`, `genres`, `books`, `related_works`
- `BookInfoBook`: `foreign_id`, `asin`, `isbn13`, `title`, `description`,
  `publisher`, `release_date`, `image_url`, `url`, `format`, `language`, `num_pages`
- `BookInfoAuthor`: `foreign_id`, `name`, `description`, `url`, `image_url`,
  `works`, `series`

All fields use `AliasChoices` to accept both `PascalCase` (the canonical
rreading-glasses output) and `camelCase` (some self-hosted forks use this).

## Caveats

- **Not all `book_id`s resolve.** The `/book/{id}` endpoint may return an empty
  body for editions that don't have a separate scraped record. `get_book` will
  return `None` in that case: fall back to `get_work(work_id)` from the search hit.
- **Public hosted instances are best-effort.** If you build anything serious
  on top, self-host. The maintainer of `rreading-glasses` is explicit about
  this in the project README.
- **Genres are a flat string list.** No taxonomy: they're whatever Goodreads
  shelves the work was tagged with. Useful for fuzzy matching, not for
  classification.

---
[← ArrMetadataClient](arr-metadata.md) · [Home](../README.md) · [OpenLibraryClient →](openlibrary.md)
