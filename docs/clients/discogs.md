# DiscogsClient

Wraps the [Discogs public REST API](https://www.discogs.com/developers/).
Authentication is optional: the API works without a token, but a personal
access token raises the rate limit significantly.

Discogs indexes music releases (vinyl, CD, cassette) and physical video media
(Blu-ray, DVD, VHS, LaserDisc, HD DVD, UHD Blu-ray). For film metadata its
strengths are:

- **Label and catalogue number**: the authoritative source for Criterion,
  Arrow, Shout Factory, and similar prestige labels.
- **VHS and LaserDisc**: the only source in metadatarr for these formats.
- **Country of release and release year**: regional edition tracking.
- **Cover images**: high-resolution primary images via `primary_image_url`.

Film coverage on Discogs is uneven. Arthouse, foreign, and older catalogue
titles are well-indexed. Mainstream blockbusters often have fewer or less
complete entries because Discogs' user base skews toward music. Always check
`search_film` results before relying on them.

## Constructor

```python
from metadatarr.client import DiscogsClient

# Without a token: 25 req/min
client = DiscogsClient()

# With a token via env var (recommended for batch work):
# export DISCOGS_TOKEN=your_token_here
client = DiscogsClient()

# Or pass the token directly:
client = DiscogsClient(token="your_token_here", timeout=15)
```

`token`: Discogs personal access token. If not passed, the constructor reads
`DISCOGS_TOKEN` from the environment. Optional, the API works without it.

`timeout`: seconds before the underlying `requests.Session` raises. Defaults
to `15`.

Rate limits: **25 req/min** unauthenticated, **60 req/min** with a token.

## Endpoints covered

| Method | Endpoint | Returns |
|---|---|---|
| `search(title, ...)` | `GET /database/search` | `List[DiscogsSearchHit]` |
| `search_film(title, ...)` | `GET /database/search` (with genre fallback) | `List[DiscogsSearchHit]` |
| `get_release(release_id)` | `GET /releases/{id}` | `Optional[DiscogsRelease]` |

## `search(title, *, fmt, media_type, genre, per_page) -> List[DiscogsSearchHit]`

Low-level search. Returns all Discogs entry types matching `title` with the
given format and genre filter. Use `search_film` for film lookups, use `search`
directly when you need full control over the query parameters.

```python
from metadatarr.client import DiscogsClient

client = DiscogsClient()

# Search for VHS releases
hits = client.search("The Terminator", fmt="VHS", genre="Non-Music")
for hit in hits:
    print(hit.id, hit.title, hit.year, hit.country, hit.label)
```

Parameters:

| Parameter | Default | Notes |
|---|---|---|
| `fmt` | `"Blu-ray"` | Discogs format string: `"Blu-ray"`, `"DVD"`, `"VHS"`, `"Laserdisc"`, `"Vinyl"`, etc. |
| `media_type` | `"release"` | `"release"` or `"master"` |
| `genre` | `None` | Optional genre filter. For film use `"Non-Music"` or `"Stage & Screen"` |
| `per_page` | `10` | Results per page, Discogs caps at `100` |

## `search_film(title, *, fmt, per_page) -> List[DiscogsSearchHit]`

Convenience wrapper for film lookups. Tries three queries in sequence and
returns the first non-empty result:

1. `genre="Non-Music"`: covers narrative films
2. `genre="Stage & Screen"`: covers concert films, documentaries
3. No genre filter: unrestricted fallback

```python
hits = client.search_film("Blade Runner 2049", fmt="Blu-ray")
if hits:
    print(hits[0].id, hits[0].title, hits[0].label)
```

Use `search_film` rather than `search` for film lookups unless you have a
specific reason to bypass the genre fallback.

## `get_release(release_id) -> Optional[DiscogsRelease]`

Fetches full release detail by Discogs numeric ID. Returns `None` on network
errors or a 404.

```python
release = client.get_release(hits[0].id)
if release:
    print(release.title, release.released)
    print("Labels:", release.label_names)
    print("Formats:", release.format_names)
    print("Artists:", release.artist_names)
    print("Cover:", release.primary_image_url)
```

## `DiscogsSearchHit` fields

| Field | Type | Notes |
|---|---|---|
| `id` | `int` | Discogs numeric release ID, use with `get_release` |
| `title` | `str` | Title as indexed by Discogs |
| `url` | `Optional[str]` | Relative URI (e.g. `/releases/12345`) |
| `cover_image` | `Optional[str]` | Thumbnail URL |

| Field | Type | Notes |
|---|---|---|
| `year` | `Optional[int]` | Parsed from Discogs `year` field |
| `format` | `List[str]` | Format names for this release |
| `label` | `List[str]` | Label name(s) |
| `country` | `Optional[str]` | Country of release |

| Field | Type | Notes |
|---|---|---|
| `catno` | `Optional[str]` | Catalogue number |

`year` is coerced from a string, it will be `None` if Discogs returns an
empty or non-numeric value.

## `DiscogsRelease` fields

| Field | Type | Notes |
|---|---|---|
| `id` | `int` | Discogs numeric release ID |
| `title` | `str` | |
| `uri` | `Optional[str]` | Relative URI |
| `year` | `Optional[int]` | |

| Field | Type | Notes |
|---|---|---|
| `released` | `Optional[str]` | Full date when known (`"2019-03-15"`) |
| `country` | `Optional[str]` | |
| `notes` | `Optional[str]` | Publisher notes |
| `formats` | `List[dict]` | Raw Discogs format objects |

| Field | Type | Notes |
|---|---|---|
| `labels` | `List[dict]` | Raw Discogs label objects |
| `artists` | `List[dict]` | Raw Discogs artist objects |
| `genres` | `List[str]` | |
| `styles` | `List[str]` | |

| Field | Type | Notes |
|---|---|---|
| `images` | `List[dict]` | Raw Discogs image objects |

`formats`, `labels`, `artists`, and `images` are kept as raw `dict` lists
because Discogs' sub-object schemas are complex and vary by release type. Use
the convenience properties instead of parsing them manually:

| Property | Type | Returns |
|---|---|---|
| `label_names` | `List[str]` | `name` from each label dict |
| `format_names` | `List[str]` | `name` from each format dict |
| `artist_names` | `List[str]` | `name` from each artist dict |
| `primary_image_url` | `Optional[str]` | URI from the `"primary"` image, or the first image |

`DiscogsRelease.label_names`: `/metadatarr/models.py:601`
`DiscogsRelease.primary_image_url`: `/metadatarr/models.py:612`

## `search` vs `search_film`

Discogs indexes both music and video Blu-rays. A plain `search("Blade Runner
2049", fmt="Blu-ray")` may return a Blu-ray Audio disc of a film score before
returning the film itself. `search_film` adds genre constraints to push film
releases to the top. The cost is two extra API calls when the constrained
searches return nothing.

For VHS and LaserDisc, genre filtering is less necessary: those formats are
almost exclusively film/video content: so you can call `search` directly:

```python
hits = client.search("Akira", fmt="Laserdisc")
hits_vhs = client.search("Akira", fmt="VHS")
```

## Rate limits

Add `time.sleep(1)` between calls in batch jobs without a token (25 req/min =
one call every 2.4 s to stay safe). With a token you can reduce the sleep to
about 1 s. The Discogs API returns `429 Too Many Requests` when the limit is
exceeded, `DiscogsClient._get` will raise `requests.exceptions.HTTPError` in
that case (not swallowed silently, unlike the scraper clients).

## Notes

- `get_release` returns `None` on any exception (network error, 404, schema
  mismatch). Check `if release is None` before accessing fields.
- `search` and `search_film` return `[]` on any exception.
- The `DiscogsProvider` resolve provider writes `discogs_label`,
  `discogs_catno`, `discogs_cover`, and `discogs_url` into `ExternalIds.extra`.
  These are available in `result.external_ids.extra` after a `resolve()` call.

---
[← DVDCompareClient](dvdcompare.md) · [Home](../README.md) · [Physical disc guide →](../physical-disc.md)
