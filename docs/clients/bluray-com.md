# BlurayComClient

Wraps [blu-ray.com](https://www.blu-ray.com) via HTML scraping. No API key or
account required. `BeautifulSoup` (included in metadatarr's `beautifulsoup4`
dependency) does the parsing.

blu-ray.com is the primary source for technical disc specifications: codec,
resolution, HDR type, per-track audio, bitrate, and regional release details.
It is strong for mainstream and catalogue releases but may not index niche
labels. Every field on `BlurayComEdition` can be `None` if the site's layout
changes or the information is absent from the page.

## Constructor

```python
from metadatarr.client import BlurayComClient

client = BlurayComClient(timeout=15)
```

`timeout` — seconds before the underlying `requests.Session` raises
`requests.exceptions.Timeout`. Defaults to `15`.

## Endpoints covered

| Method | Scrapes | Returns |
|---|---|---|
| `search(title)` | `/movies/search.php?keyword=…&section=bluraymovies` | `List[BlurayComSearchHit]` |
| `get_edition(bluray_com_id)` | `/movies/redirect.php?id=…` (follows redirect to detail page) | `Optional[BlurayComEdition]` |
| `get_edition_by_url(url)` | The URL directly | `Optional[BlurayComEdition]` |

## `search(title) -> List[BlurayComSearchHit]`

Returns a list of search hits. The first hit is usually the best match. Use
`get_edition` or `get_edition_by_url` to fetch full specs for any hit.

```python
from metadatarr.client import BlurayComClient

client = BlurayComClient()
hits = client.search("Annihilation")

for hit in hits:
    print(hit.bluray_com_id, hit.title, hit.year, hit.rating)
```

`BlurayComSearchHit` fields:

| Field | Type | Notes |
|---|---|---|
| `bluray_com_id` | `int` | Numeric page ID; stable identifier |
| `title` | `str` | As listed on the search results page |
| `year` | `Optional[int]` | Release year scraped from the listing |
| `url` | `Optional[str]` | Full URL to the detail page |
| `cover_url` | `Optional[str]` | Thumbnail image URL |
| `rating` | `Optional[float]` | Community rating shown in search results |

## `get_edition(bluray_com_id) -> Optional[BlurayComEdition]`

Fetches the full technical-spec page for a known numeric ID.

```python
edition = client.get_edition(149811)
if edition:
    print(edition.title, edition.hdr, edition.video_codec)
    print(edition.resolution, edition.video_bitrate_kbps, "kbps")
    for track in edition.audio_tracks:
        print(track.codec, track.channels, track.language)
```

## `get_edition_by_url(url) -> Optional[BlurayComEdition]`

Same as `get_edition` but takes a full URL rather than a numeric ID. Useful
when you already have the URL from a search hit.

```python
edition = client.get_edition_by_url(
    "https://www.blu-ray.com/movies/Annihilation-Blu-ray/149811/"
)
```

## `BlurayComEdition` fields

| Field | Type | Notes |
|---|---|---|
| `bluray_com_id` | `int` | Numeric page ID |
| `title` | `str` | Title as shown on the detail page |
| `year` | `Optional[int]` | |
| `url` | `Optional[str]` | Detail page URL |
| `cover_url` | `Optional[str]` | Front cover image |
| `disc_format` | `Optional[str]` | `"Blu-ray"`, `"4K UHD Blu-ray"`, `"DVD"` |
| `region` | `Optional[str]` | `"A"`, `"B"`, `"C"`, `"Free"` |
| `disc_count` | `Optional[int]` | Number of discs in the set |
| `resolution` | `Optional[str]` | `"1080p"`, `"2160p"` |
| `aspect_ratio` | `Optional[str]` | `"2.39:1"`, `"1.78:1"`, etc. |
| `video_codec` | `Optional[str]` | `"HEVC"`, `"AVC"`, `"VC-1"` |
| `video_bitrate_kbps` | `Optional[int]` | Average or max video bitrate |
| `hdr` | `Optional[str]` | `"HDR10"`, `"Dolby Vision"`, `"HDR10+"` |
| `audio_tracks` | `List[BlurayComAudioTrack]` | Per-track codec/channel/language data |
| `studio` | `Optional[str]` | Production studio |
| `label` | `Optional[str]` | Distributor label (`"Criterion"`, `"Arrow"`, …) |
| `release_date` | `Optional[str]` | Street date, format varies |
| `runtime_minutes` | `Optional[int]` | |
| `has_slipcover` | `Optional[bool]` | `True` if the listing notes a slipcover |
| `imdb_id` | `Optional[str]` | `tt`-prefixed ID scraped from page links |
| `rating` | `Optional[float]` | Community rating |
| `extras` | `List[str]` | Special feature titles |

## `BlurayComAudioTrack` fields

| Field | Type | Notes |
|---|---|---|
| `codec` | `Optional[str]` | `"Dolby Atmos"`, `"DTS-HD MA 7.1"`, `"PCM"`, etc. |
| `channels` | `Optional[str]` | `"7.1"`, `"5.1"`, `"2.0"` |
| `language` | `Optional[str]` | Human-readable language name |
| `bitrate_kbps` | `Optional[int]` | Track bitrate; often `None` |

## Known limitations and scraper fragility

blu-ray.com is an HTML scraper, not a documented API. The CSS selectors used
to extract specs (`td`, `li`, `div.specrow`) and audio tracks (`table#audio`,
`div#audio`, `div.audio-specs`) reflect the site's layout as of the time this
code was written. If the site redesigns, fields will silently return `None`
rather than raising an exception.

To adapt to a layout change without forking the whole client, subclass and
override `_parse_edition_page` (or the inner `_spec` helper by re-implementing
that method on the subclass):

```python
from typing import Optional
from bs4 import BeautifulSoup
from metadatarr.client import BlurayComClient, BlurayComEdition


class PatchedBlurayClient(BlurayComClient):
    def _parse_edition_page(
        self, soup: BeautifulSoup, bid: int, url: Optional[str]
    ) -> Optional[BlurayComEdition]:
        # Your updated parsing logic here.
        ...
```

`BlurayComClient._parse_edition_page` — `/metadatarr/client.py:562`

## Notes

- All methods return `[]` or `None` on network errors — the scraper never
  raises to the caller.
- Add `time.sleep(1)` between calls in any batch job. blu-ray.com has no
  published rate limit, but sustained scraping at high frequency risks a
  temporary block.
- The numeric `bluray_com_id` appears in every detail page URL and is stable
  across site updates.
