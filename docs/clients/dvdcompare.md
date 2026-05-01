# DVDCompareClient

Wraps [dvdcompare.net](https://www.dvdcompare.net) via HTML scraping. No API
key or account required.

DVDCompare's primary value is **explicit version metadata**: the `version`
field tells you whether a disc carries the Director's Cut, Theatrical, or
Extended cut, and `version_differences` provides a free-text description of
what changed between editions. No other source in metadatarr surfaces this
information in structured form.

## Constructor

```python
from metadatarr.client import DVDCompareClient

client = DVDCompareClient(timeout=15)
```

`timeout` — seconds before the underlying `requests.Session` raises. Defaults
to `15`.

## Endpoints covered

| Method | Scrapes | Returns |
|---|---|---|
| `search(title)` | `/comparisons/dvdsearch.php?title=…` | `List[DVDCompareEdition]` |
| `get_edition(url)` | The edition comparison page URL | `Optional[DVDCompareEdition]` |

## `search(title) -> List[DVDCompareEdition]`

Returns a list of matching editions. Search results carry only the fields
visible in the results table (title, label, region, release date, URL). Call
`get_edition` with a result's `url` to retrieve the full version/audio/
subtitle data.

```python
from metadatarr.client import DVDCompareClient

client = DVDCompareClient()
results = client.search("Blade Runner 2049")

for ed in results:
    print(ed.title, ed.region, ed.label, ed.url)
```

## `get_edition(url) -> Optional[DVDCompareEdition]`

Fetches the full detail page for a specific edition. Pass the `url` from a
search hit or any dvdcompare.net comparison page URL.

```python
if results:
    detail = client.get_edition(results[0].url)
    if detail:
        print("Version:", detail.version)
        print("Differences:", detail.version_differences)
        print("Audio:", detail.audio_tracks)
        print("Subtitles:", detail.subtitles)
        print("Extras:", detail.extras)
```

## `DVDCompareEdition` fields

| Field | Type | Notes |
|---|---|---|
| `dvdcompare_id` | `Optional[str]` | Slug derived from the page URL |
| `title` | `str` | |
| `url` | `Optional[str]` | Full URL to the comparison page |
| `disc_format` | `Optional[str]` | `"Blu-ray"`, `"DVD"`, `"4K UHD"` |
| `region` | `Optional[str]` | DVD/Blu-ray region code |
| `country` | `Optional[str]` | Country of release |
| `label` | `Optional[str]` | Distributor label |
| `release_date` | `Optional[str]` | Date string, format varies |
| `runtime_minutes` | `Optional[int]` | |
| `aspect_ratio` | `Optional[str]` | |
| `version` | `Optional[str]` | `"Director's Cut"`, `"Theatrical"`, `"Extended"`, etc. |
| `version_differences` | `Optional[str]` | Free-text description of what differs |
| `audio_tracks` | `List[str]` | Each element is a plain string (e.g. `"English DTS-HD MA 5.1"`) |
| `subtitles` | `List[str]` | Each element is a plain string (e.g. `"English SDH"`) |
| `extras` | `List[str]` | Special feature titles |
| `imdb_id` | `Optional[str]` | `tt`-prefixed, scraped from page links |

`audio_tracks` and `subtitles` are lists of raw strings as they appear on the
dvdcompare page. They are not parsed into structured objects. If you need
codec/channel splits, apply your own string parsing.

## Version field and VariantKind mapping

The `version` field is free text from the site. The `dvdcompare` provider
(used via the resolve system) maps it to `VariantKind` automatically using
keyword matching:

| `version` contains | `VariantKind` |
|---|---|
| `"director"` | `DIRECTORS` |
| `"theatrical"` | `THEATRICAL` |
| `"extended"` | `EXTENDED` |
| `"remaster"` | `REMASTERED` |
| `"regional"` | `REGIONAL` |

If none of these keywords match, `variant_kind` is left unset — the candidate
still participates in consolidation without constraining which cut is selected.

`_infer_variant` — `/metadatarr/resolve/providers/dvdcompare.py:32`

## Notes

- All methods return `[]` or `None` on network errors.
- Add `time.sleep(1)` between calls in batch jobs. dvdcompare.net has no
  published rate limit.
- The search result objects (`DVDCompareEdition` returned by `search`) have
  sparse fields. Always call `get_edition` to retrieve `version`,
  `audio_tracks`, `subtitles`, and `extras`.
- `dvdcompare_id` is derived from the URL slug and may change if the site
  reorganises its URL structure. It is not a stable numeric ID. Store the URL
  (`dvdcompare_url` extra key) as the durable reference if you persist results.
