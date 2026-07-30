# OpenLibraryClient

Wraps the [OpenLibrary REST API](https://openlibrary.org/developers/api).
OpenLibrary is the Internet Archive's open book metadata project: fully
public, no key, generous rate limits (be polite anyway).

```python
from metadatarr import OpenLibraryClient
ol = OpenLibraryClient()
```

## Mental model

OpenLibrary distinguishes three entity types, each with an `OL…` ID:

| Entity | Key shape | Example | What it is |
|---|---|---|---|
| **Work** | `OL…W` | `OL45804W` | The abstract book ("Fantastic Mr Fox", regardless of printing) |
| **Edition** | `OL…M` | `OL32848840M` | A specific printing (publisher, ISBN, year) |
| **Author** | `OL…A` | `OL34184A` | A person |

Search returns work-level hits with a hint at the best cover edition.

## Endpoints

| Method | Returns | Upstream |
|---|---|---|
| `search(query, limit=10)` | `list[OpenLibrarySearchHit]` | `GET /search.json?q=&limit=` |
| `get_work(OLID)` | `OpenLibraryWork \| None` | `GET /works/{id}.json` |
| `get_edition(OLID)` | `OpenLibraryEdition \| None` | `GET /books/{id}.json` |
| `get_edition_by_isbn(isbn)` | `OpenLibraryEdition \| None` | `GET /isbn/{isbn}.json` |

| Method | Returns | Upstream |
|---|---|---|
| `get_author(OLID)` | `OpenLibraryAuthor \| None` | `GET /authors/{id}.json` |
| `cover_url(cover_id, size)` *(staticmethod)* | `str` | `https://covers.openlibrary.org/b/id/{id}-{S\|M\|L}.jpg` |

## A complete walkthrough

```python
from metadatarr import OpenLibraryClient

ol = OpenLibraryClient()

# 1. Search returns lightweight hits
hits = ol.search("the dispossessed le guin", limit=3)
hit = hits[0]
print(hit.title, hit.first_publish_year, hit.work_id, hit.author_names)

# 2. Pivot to the work for description, subjects, all author keys
work = ol.get_work(hit.work_id)        # accepts 'OL…W' or '/works/OL…W'
print(work.title)
print(work.description[:200] if work.description else "(no description)")
print("subjects:", work.subjects[:5])

# 3. Author bio
if work.author_keys:
    author = ol.get_author(work.author_keys[0])
    print(author.name, author.birth_date, "-", author.death_date)
    print((author.bio or "")[:200])

# 4. Resolve a specific edition by ISBN
edition = ol.get_edition_by_isbn("9780061054884")
print(edition.title, edition.publishers, edition.number_of_pages, edition.isbn_13)
print("parent works:", edition.work_keys)

# 5. Cover image
if hit.cover_id:
    print(OpenLibraryClient.cover_url(hit.cover_id, size="L"))
```

## ID handling

OpenLibrary returns "keys" with leading slashes (`/works/OL45804W`,
`/authors/OL34184A`). metadatarr **strips the prefix** in models so you always
work with bare OLIDs:

```python
work.key            # "OL45804W"          (not "/works/OL45804W")
work.author_keys    # ["OL34184A", ...]   (not ["/authors/OL34184A", ...])
edition.work_keys   # ["OL45804W", ...]
edition.languages   # ["eng", ...]        (not ["/languages/eng", ...])
```

`get_work`, `get_edition`, and `get_author` all accept either form: they
call `.split("/")[-1]` defensively.

## Description / bio normalisation

OpenLibrary serialises long-form text inconsistently. Sometimes:

```json
"description": "A short string"
```

Sometimes:

```json
"description": {"type": "/type/text", "value": "The actual text"}
```

metadatarr's models flatten both into a plain `str | None`. You read
`work.description` and never have to care.

## Cover URLs

```python
OpenLibraryClient.cover_url(cover_id, size="L")
```

Where `size` is `"S"` (small, ~96px), `"M"` (medium, ~180px), or `"L"`
(large, ~500px). Anything else falls back to `L`.

For ISBN-based covers (when you don't have a `cover_i`):

```python
f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"
```

(This isn't wrapped in a method: it's a one-liner and OpenLibrary's URL is
stable.)

## Search query syntax

`/search.json?q=` accepts the same search syntax as openlibrary.org's UI:

```python
ol.search("title:dune author:herbert")
ol.search("isbn:9780441172719")
ol.search("subject:cyberpunk first_publish_year:[1980 TO 1995]")
```

The `OpenLibrarySearchHit` model exposes only the most-used fields. If you
need more (`ia` archive identifiers, `ratings_average`, etc.) extend the
model: see [Extending models](../models.md#extending-models).

## Models

See [Models reference → OpenLibrary*](../models.md#openlibrary).

## Caveats

- **Search is fuzzy and big.** A search for "dune" returns ~50,000 hits.
  Always pass a tight `limit=` and supply `author:` or `isbn:` qualifiers
  when you have them.
- **`get_edition_by_isbn` may 302 to a canonical edition.** `requests`
  follows redirects by default, you'll get the canonical edition, which is
  almost always what you want.
- **OpenLibrary data is community-edited.** Expect some records to have
  obviously wrong dates, missing publishers, or duplicate works. Treat it
  as a strong-but-not-authoritative source.

---
[← BookInfoClient](bookinfo.md) · [Home](../README.md) · [AnnasArchiveClient →](annas-archive.md)
