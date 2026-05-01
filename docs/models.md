# Models reference

All models live in `metadatarr.models` and are Pydantic V2 `BaseModel`s. Every
model uses `model_config = ConfigDict(populate_by_name=True)` so you can
construct them either by alias (the upstream JSON shape) or by canonical
Python name.

## Servarr (TV / movies / music)

### `BaseMetadata`

Shared parent for the *arr models. You won't construct this directly.

| Field | Aliases | Notes |
|---|---|---|
| `title` | `title`, `Title`, `artistName`, `ArtistName`, `artistname`, `name` | Canonical display name |
| `overview` | nested `Artist.Overview` / `Artist.Description`, `overview`, `Overview`, `Description` | Long description |

### `SonarrSeries(BaseMetadata)`

| Field | Type | Source |
|---|---|---|
| `tvdb_id` | `int` | `tvdbId` |
| `year` | `Optional[int]` | `year` |

### `RadarrMovie(BaseMetadata)`

| Field | Type | Source |
|---|---|---|
| `tmdb_id` | `int` | `tmdbId`, `TmdbId` |
| `year` | `Optional[int]` | `year`, `Year` |

### `LidarrArtist(BaseMetadata)`

| Field | Type | Source |
|---|---|---|
| `id` | `str` | `Artist.Id`, `id`, `artistId`, `Id` |
| `name` | `str` | `Artist.ArtistName`, `artistName`, etc. |
| `overview` | `Optional[str]` | nested or flat |

`id` is a MusicBrainz UUID string (e.g. `"056e4f3e-d505-4dad-8ec1-d04f521cbb56"`).

## BookInfo

Used by `BookInfoClient` (rreading-glasses).

### `BookInfoSearchHit`

| Field | Type | Source |
|---|---|---|
| `book_id` | `int` | `bookId`, `BookId` |
| `work_id` | `int` | `workId`, `WorkId` |
| `author_id` | `Optional[int]` | nested `author.id` / `Author.Id` |

### `BookInfoBook` (an edition / printing)

| Field | Type | Notes |
|---|---|---|
| `foreign_id` | `int` | The edition's own ID |
| `asin` | `Optional[str]` | Amazon ASIN |
| `isbn13` | `Optional[str]` | |
| `title` | `Optional[str]` | Edition-level title (often = work title) |
| `description` | `Optional[str]` | Per-edition blurb |
| `publisher` | `Optional[str]` | |
| `release_date` | `Optional[str]` | ISO-ish, format varies |
| `image_url` | `Optional[str]` | Cover URL |
| `url` | `Optional[str]` | Upstream page |
| `format` | `Optional[str]` | `"Hardcover"`, `"Paperback"`, `"ebook"`, etc. |
| `language` | `Optional[str]` | |
| `num_pages` | `Optional[int]` | |

### `BookInfoWork`

| Field | Type | Notes |
|---|---|---|
| `foreign_id` | `int` | The work ID |
| `title` | `str` | Canonical title |
| `full_title` | `Optional[str]` | Including subtitle / series number |
| `short_title` | `Optional[str]` | Stripped form |
| `url` | `Optional[str]` | Upstream page (Goodreads or Hardcover) |
| `release_date` | `Optional[str]` | First-published, formatted |
| `release_date_raw` | `Optional[str]` | First-published, raw `YYYY-MM-DD` |
| `genres` | `list[str]` | Flat list |
| `books` | `list[BookInfoBook]` | All known editions |
| `related_works` | `list[int]` | IDs of related works (other in series, etc.) |

### `BookInfoAuthor`

| Field | Type | Notes |
|---|---|---|
| `foreign_id` | `int` | |
| `name` | `str` | |
| `description` | `Optional[str]` | Bio |
| `url` | `Optional[str]` | |
| `image_url` | `Optional[str]` | Author photo |
| `works` | `list[BookInfoWork]` | All works by author (may be partial) |
| `series` | `list[dict]` | Raw — series metadata schema is unstable, kept as `dict` |

## OpenLibrary

Used by `OpenLibraryClient`. All `key` fields are bare OLIDs — leading
`/works/`, `/authors/`, `/books/`, `/languages/` prefixes are stripped.

### `OpenLibrarySearchHit`

| Field | Type | Source |
|---|---|---|
| `work_key` | `Optional[str]` | `key` (full path; bare ID via `.work_id` property) |
| `title` | `Optional[str]` | |
| `author_names` | `list[str]` | `author_name` |
| `author_keys` | `list[str]` | `author_key` (bare OLIDs) |
| `first_publish_year` | `Optional[int]` | |
| `edition_count` | `Optional[int]` | |
| `cover_id` | `Optional[int]` | `cover_i` — feed to `cover_url()` |
| `cover_edition_key` | `Optional[str]` | The OLID of the edition that has the cover |
| `isbn` | `list[str]` | All ISBNs across all known editions |
| `language` | `list[str]` | |

`hit.work_id` is a derived property: returns the bare OLID without the
`/works/` prefix.

### `OpenLibraryWork`

| Field | Type | Notes |
|---|---|---|
| `key` | `str` | Bare `OL…W` |
| `title` | `str` | |
| `description` | `Optional[str]` | Flattened from `str` or `{type, value}` |
| `subjects` | `list[str]` | Free-form tags |
| `covers` | `list[int]` | Cover IDs in priority order |
| `first_publish_date` | `Optional[str]` | |
| `author_keys` | `list[str]` | Bare `OL…A` IDs |

> 💡 The author entries on a work are nested: each item is
> `{"author": {"key": "/authors/OL…A"}, "type": {...}}`. The `from_api()`
> classmethod walks that structure for you.

### `OpenLibraryEdition`

| Field | Type | Notes |
|---|---|---|
| `key` | `str` | Bare `OL…M` |
| `title` | `str` | |
| `subtitle` | `Optional[str]` | |
| `isbn_10` | `list[str]` | |
| `isbn_13` | `list[str]` | |
| `publishers` | `list[str]` | |
| `publish_date` | `Optional[str]` | |
| `number_of_pages` | `Optional[int]` | |
| `languages` | `list[str]` | Bare codes (`"eng"`, not `"/languages/eng"`) |
| `covers` | `list[int]` | |
| `work_keys` | `list[str]` | Parent works (almost always 1) |

### `OpenLibraryAuthor`

| Field | Type | Notes |
|---|---|---|
| `key` | `str` | Bare `OL…A` |
| `name` | `str` | Falls back to `personal_name` if `name` missing |
| `personal_name` | `Optional[str]` | |
| `bio` | `Optional[str]` | Flattened from `str` or `{type, value}` |
| `birth_date` | `Optional[str]` | Free-form (`"31 July 1965"`, `"1920"`, …) |
| `death_date` | `Optional[str]` | |
| `photos` | `list[int]` | Photo IDs (negatives filtered out — OL uses `-1` as a sentinel) |

## Anna's Archive

### `AnnasArchiveBook`

| Field | Type | Notes |
|---|---|---|
| `title` | `str` | |
| `author` | `str` | |
| `formats` | `Optional[str]` | Uppercased |
| `md5` | `str` | The durable identifier |
| `cover_url` | `Optional[str]` | May be relative |
| `language` | `Optional[str]` | |
| `size` | `Optional[str]` | Human readable |

## Physical disc

Models for blu-ray.com, dvdcompare.net, and Discogs. All live in
`metadatarr.models`; import them from `metadatarr.client` is not required
unless you are instantiating a client.

### `BlurayComAudioTrack`

A single audio track as reported by blu-ray.com.

| Field | Type | Notes |
|---|---|---|
| `codec` | `Optional[str]` | `"Dolby Atmos"`, `"DTS-HD MA 7.1"`, `"PCM"`, etc. |
| `channels` | `Optional[str]` | `"7.1"`, `"5.1"`, `"2.0"` |
| `language` | `Optional[str]` | Human-readable language name |
| `bitrate_kbps` | `Optional[int]` | Track bitrate; often `None` |

`BlurayComAudioTrack` — `/metadatarr/models.py:475`

### `BlurayComSearchHit`

A single result from a blu-ray.com search. Returned by
`BlurayComClient.search`.

| Field | Type | Notes |
|---|---|---|
| `bluray_com_id` | `int` | Stable numeric page ID |
| `title` | `str` | |
| `year` | `Optional[int]` | |
| `url` | `Optional[str]` | Full URL to the detail page |
| `cover_url` | `Optional[str]` | Thumbnail image URL |
| `rating` | `Optional[float]` | Community rating |

`BlurayComSearchHit` — `/metadatarr/models.py:484`

### `BlurayComEdition`

Full disc detail from a blu-ray.com movie page. Returned by
`BlurayComClient.get_edition` and `get_edition_by_url`.

| Field | Type | Notes |
|---|---|---|
| `bluray_com_id` | `int` | Numeric page ID |
| `title` | `str` | |
| `year` | `Optional[int]` | |
| `url` | `Optional[str]` | Detail page URL |
| `cover_url` | `Optional[str]` | Front cover image |
| `disc_format` | `Optional[str]` | `"Blu-ray"`, `"4K UHD Blu-ray"`, `"DVD"` |
| `region` | `Optional[str]` | `"A"`, `"B"`, `"C"`, `"Free"` |
| `disc_count` | `Optional[int]` | Number of discs |
| `resolution` | `Optional[str]` | `"1080p"`, `"2160p"` |
| `aspect_ratio` | `Optional[str]` | `"2.39:1"`, `"1.78:1"`, etc. |
| `video_codec` | `Optional[str]` | `"HEVC"`, `"AVC"`, `"VC-1"` |
| `video_bitrate_kbps` | `Optional[int]` | Average or max video bitrate |
| `hdr` | `Optional[str]` | `"HDR10"`, `"Dolby Vision"`, `"HDR10+"` |
| `audio_tracks` | `List[BlurayComAudioTrack]` | Per-track data |
| `studio` | `Optional[str]` | Production studio |
| `label` | `Optional[str]` | Distributor label (`"Criterion"`, `"Arrow"`, …) |
| `release_date` | `Optional[str]` | Street date, format varies |
| `runtime_minutes` | `Optional[int]` | |
| `has_slipcover` | `Optional[bool]` | |
| `imdb_id` | `Optional[str]` | `tt`-prefixed, scraped from page links |
| `rating` | `Optional[float]` | Community rating |
| `extras` | `List[str]` | Special feature titles |

`BlurayComEdition` — `/metadatarr/models.py:495`

### `DVDCompareEdition`

A regional disc edition from dvdcompare.net. Returned by
`DVDCompareClient.search` (sparse) and `get_edition` (full).

| Field | Type | Notes |
|---|---|---|
| `dvdcompare_id` | `Optional[str]` | Slug from the page URL |
| `title` | `str` | |
| `url` | `Optional[str]` | Full URL to the comparison page |
| `disc_format` | `Optional[str]` | `"Blu-ray"`, `"DVD"`, `"4K UHD"` |
| `region` | `Optional[str]` | |
| `country` | `Optional[str]` | |
| `label` | `Optional[str]` | |
| `release_date` | `Optional[str]` | |
| `runtime_minutes` | `Optional[int]` | |
| `aspect_ratio` | `Optional[str]` | |
| `version` | `Optional[str]` | `"Director's Cut"`, `"Theatrical"`, `"Extended"`, etc. |
| `version_differences` | `Optional[str]` | Free-text description of what differs |
| `audio_tracks` | `List[str]` | Plain strings; not parsed into structured objects |
| `subtitles` | `List[str]` | Plain strings |
| `extras` | `List[str]` | Special feature titles |
| `imdb_id` | `Optional[str]` | `tt`-prefixed, scraped from page links |

`DVDCompareEdition` — `/metadatarr/models.py:532`

### `DiscogsSearchHit`

A single hit from the Discogs database search API. Returned by
`DiscogsClient.search` and `search_film`.

| Field | Type | Notes |
|---|---|---|
| `id` | `int` | Discogs numeric release ID; use with `get_release` |
| `title` | `str` | |
| `url` | `Optional[str]` | Relative URI (e.g. `/releases/12345`) |
| `cover_image` | `Optional[str]` | Thumbnail URL |
| `year` | `Optional[int]` | Coerced from string; `None` if non-numeric |
| `format` | `List[str]` | Format names |
| `label` | `List[str]` | Label name(s) |
| `country` | `Optional[str]` | |
| `catno` | `Optional[str]` | Catalogue number |

`DiscogsSearchHit` — `/metadatarr/models.py:558`

### `DiscogsRelease`

Full release detail from the Discogs releases API. Returned by
`DiscogsClient.get_release`.

| Field | Type | Notes |
|---|---|---|
| `id` | `int` | Discogs numeric release ID |
| `title` | `str` | |
| `uri` | `Optional[str]` | Relative URI |
| `year` | `Optional[int]` | |
| `released` | `Optional[str]` | Full date when known (`"2019-03-15"`) |
| `country` | `Optional[str]` | |
| `notes` | `Optional[str]` | Publisher notes |
| `formats` | `List[dict]` | Raw Discogs format objects |
| `labels` | `List[dict]` | Raw Discogs label objects |
| `artists` | `List[dict]` | Raw Discogs artist objects |
| `genres` | `List[str]` | |
| `styles` | `List[str]` | |
| `images` | `List[dict]` | Raw Discogs image objects |

Convenience properties (avoid parsing the raw dicts manually):

| Property | Type | Returns |
|---|---|---|
| `label_names` | `List[str]` | `name` from each label dict |
| `format_names` | `List[str]` | `name` from each format dict |
| `artist_names` | `List[str]` | `name` from each artist dict |
| `primary_image_url` | `Optional[str]` | URI of the `"primary"` image, or the first image |

`DiscogsRelease` — `/metadatarr/models.py:580`

Also see [ExternalIds — physical disc fields](resolve.md#externalids):
`discogs_release`, `bluray_com_id`, `dvdcompare_id`.

## Extending models

If you need a field metadatarr doesn't expose, subclass and add it. Pydantic V2
makes this cheap:

```python
from typing import Optional
from pydantic import Field, AliasChoices
from metadatarr.models import SonarrSeries

class FatSonarrSeries(SonarrSeries):
    network: Optional[str] = Field(None, validation_alias=AliasChoices("network", "Network"))
    runtime: Optional[int] = None
```

Then validate manually if you don't want to subclass the client too:

```python
import requests
raw = requests.get("https://skyhook.sonarr.tv/v1/tvdb/search/en/", params={"term": "Severance"}).json()
results = [FatSonarrSeries.model_validate(r) for r in raw]
```

For ergonomic reuse, subclass the client and override the call:

```python
from metadatarr import ArrMetadataClient

class FatArr(ArrMetadataClient):
    def search_series(self, term):
        url = f"{self.endpoints['sonarr']}/tvdb/search/en/"
        data = self._get(url, params={"term": term})
        return [FatSonarrSeries.model_validate(item) for item in data] if isinstance(data, list) else []
```
