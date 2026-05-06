# Physical disc metadata

metadatarr includes three clients and three resolver providers for physical
disc releases: blu-ray.com, dvdcompare.net, and Discogs. This guide covers
when to use each, how to use them from scratch, and how they compose in the
resolver.

## What each source is good for

### blu-ray.com

Technical specifications for Blu-ray and 4K UHD disc releases: video codec,
resolution, HDR type, video bitrate, per-track audio (codec, channels,
language), aspect ratio, region, disc count, label, extras list, and slipcover
presence. The site covers mainstream and catalogue theatrical releases well.
Use it when you need to compare technical quality between editions or identify
which region's disc has Dolby Vision.

### dvdcompare.net

Regional edition comparison with explicit version metadata. The `version` field
carries structured cut information ("Director's Cut", "Theatrical", "Extended")
and `version_differences` provides a free-text description of what changed
between editions. This is the only source in metadatarr that makes the
Director's Cut / Theatrical distinction in a structured field. Use it for cut
and version disambiguation.

### Discogs

The public Discogs database covers both music and physical video media including
Blu-ray, DVD, VHS, and LaserDisc. Discogs is the authoritative source for:
label and catalogue number (Criterion Collection SPINE-###, Arrow Video, Shout
Factory), country and year of release for regional pressings, VHS and LaserDisc
releases that blu-ray.com does not index, and high-resolution cover images.

Discogs' film coverage is uneven. It is strong for arthouse, foreign, and
older-format releases (VHS, LaserDisc, early DVD). Mainstream blockbuster
Blu-rays from major studios are often present but may have incomplete metadata.
Always verify results before relying on them.

## 5-minute quickstart

### blu-ray.com

```python
from metadatarr.client import BlurayComClient

client = BlurayComClient()

# Search by title
hits = client.search("Blade Runner 2049")
for hit in hits[:3]:
    print(hit.bluray_com_id, hit.title, hit.year)

# Fetch full specs for the first result
if hits:
    edition = client.get_edition(hits[0].bluray_com_id)
    if edition:
        print(edition.hdr, edition.video_codec, edition.resolution)
        print(edition.video_bitrate_kbps, "kbps")
        for track in edition.audio_tracks:
            print(track.codec, track.channels, track.language)
```

### dvdcompare.net

```python
from metadatarr.client import DVDCompareClient

client = DVDCompareClient()

# Search returns sparse results
results = client.search("Apocalypse Now")
for r in results[:3]:
    print(r.title, r.region, r.label, r.url)

# Fetch the full edition page to get version data
if results:
    detail = client.get_edition(results[0].url)
    if detail:
        print("Version:", detail.version)
        print("Differences:", detail.version_differences)
        print("Audio:", detail.audio_tracks)
        print("Subtitles:", detail.subtitles)
```

### Discogs

```python
from metadatarr.client import DiscogsClient

client = DiscogsClient()  # reads DISCOGS_TOKEN env var if set

# search_film tries Non-Music, then Stage & Screen, then unrestricted
hits = client.search_film("2001 A Space Odyssey", fmt="Blu-ray")
for hit in hits[:3]:
    print(hit.id, hit.title, hit.label, hit.catno)

# Full release detail
if hits:
    release = client.get_release(hits[0].id)
    if release:
        print(release.label_names)
        print(release.primary_image_url)
        print(release.released)
```

## Version / cut disambiguation

dvdcompare.net's `version` field is the most direct source for cut
information. It maps to `VariantKind` in the resolve system as follows:

| `version` contains | `VariantKind` set by provider |
|---|---|
| `"director"` | `DIRECTORS` |
| `"theatrical"` | `THEATRICAL` |
| `"extended"` | `EXTENDED` |
| `"remaster"` | `REMASTERED` |
| `"regional"` | `REGIONAL` |

### Worked example: Director's Cut vs Theatrical

```python
import metadatarr.resolve.providers  # registers all providers
from metadatarr.resolve.base import resolve
from mediavocab import Signals, MediaType, VariantKind

# Resolve the Director's Cut specifically
dc_result = resolve(Signals(
    title="Apocalypse Now",
    medium=MediaType.MOVIE,
    variant_kind=VariantKind.DIRECTORS,
))

# Resolve the Theatrical cut
theatrical_result = resolve(Signals(
    title="Apocalypse Now",
    medium=MediaType.MOVIE,
    variant_kind=VariantKind.THEATRICAL,
))

print("DC providers:", [m.provider for m in dc_result.accepted])
print("Theatrical providers:", [m.provider for m in theatrical_result.accepted])

# Check what the dvdcompare provider emitted
dc_version = dc_result.external_ids.extra.get("dvdcompare_version")
print("Version from dvdcompare:", dc_version)
```

When you pass `variant_kind=VariantKind.DIRECTORS`, `consolidate()` drops any
provider match that returns a conflicting `variant_kind` (e.g. `THEATRICAL`).
A match with no `variant_kind` set is never dropped on this basis — it simply
doesn't vote on the cut.

See [resolve.md — VariantKind](resolve.md#variantkind) for the full conflict
detection rules.

## Technical spec deep-dive

`BlurayComEdition` carries enough data to select the best disc for a given
technical requirement. Example: find the HDR10+ disc with the highest video
bitrate among all Region A pressings of a title:

```python
from metadatarr.client import BlurayComClient
import time

client = BlurayComClient()

def best_region_a_disc(title: str):
    hits = client.search(title)
    candidates = []
    for hit in hits:
        edition = client.get_edition(hit.bluray_com_id)
        time.sleep(1)  # be polite
        if edition is None:
            continue
        if edition.region not in ("A", "Free"):
            continue
        candidates.append(edition)

    # Score: prefer HDR10+ over HDR10 over SDR, then highest bitrate
    def score(ed):
        hdr_score = {"HDR10+": 3, "Dolby Vision": 2, "HDR10": 1}.get(
            ed.hdr or "", 0
        )
        return (hdr_score, ed.video_bitrate_kbps or 0)

    candidates.sort(key=score, reverse=True)
    return candidates[0] if candidates else None

best = best_region_a_disc("Mad Max Fury Road")
if best:
    print(best.title, best.hdr, best.video_bitrate_kbps)
```

## Label and catalogue number workflow

Use Discogs to identify prestige label releases and their catalogue numbers:

```python
from metadatarr.client import DiscogsClient

client = DiscogsClient()

# Find all Criterion releases of a film
hits = client.search_film("Andrei Rublev", fmt="Blu-ray")
criterion_hits = [h for h in hits if any("Criterion" in l for l in h.label)]

for hit in criterion_hits:
    print(hit.title, hit.catno, hit.country)
    release = client.get_release(hit.id)
    if release:
        print("Spine:", release.label_names, release.released)
        print("Cover:", release.primary_image_url)
```

### Enrichment via ExternalIds.discogs_release

If a `resolve()` result already carries a `discogs_release` ID (set by the
`discogs` provider), the `DiscogsProvider.enrich()` method fetches full label
and image data without re-running a search:

```python
import metadatarr.resolve.providers
from metadatarr.resolve.base import resolve
from mediavocab import Signals, MediaType
from metadatarr.resolve.providers.discogs import DiscogsProvider

result = resolve(Signals(title="Andrei Rublev", medium=MediaType.MOVIE))

discogs_id = result.external_ids.discogs_release
if discogs_id:
    provider = DiscogsProvider()
    enriched = provider.enrich(result.external_ids)
    if enriched:
        print("Label:", enriched.extra.get("discogs_label"))
        print("Cover:", enriched.extra.get("discogs_cover"))
```

`DiscogsProvider.enrich` — `/metadatarr/resolve/providers/discogs.py:109`

## VHS and LaserDisc

Discogs is the only source in metadatarr for VHS and LaserDisc releases. Use
`DiscogsClient.search` directly with the appropriate format string:

```python
from metadatarr.client import DiscogsClient

client = DiscogsClient()

# VHS
vhs_hits = client.search("Akira", fmt="VHS")
for hit in vhs_hits:
    print(hit.title, hit.year, hit.country, hit.label)

# LaserDisc
ld_hits = client.search("Akira", fmt="Laserdisc")
for hit in ld_hits:
    release = client.get_release(hit.id)
    if release:
        print(release.title, release.released, release.label_names)
```

For VHS and LaserDisc, passing a genre filter is usually not necessary since
these formats are almost exclusively film/video content. Use `search` rather
than `search_film` to skip the extra API calls.

## Using the resolver

All three providers self-register when `metadatarr.resolve.providers` is
imported. `resolve()` fans them out automatically:

```python
import metadatarr.resolve.providers
from metadatarr.resolve.base import resolve
from mediavocab import Signals, MediaType

result = resolve(Signals(
    title="Blade Runner 2049",
    medium=MediaType.MOVIE,
    source_format="Blu-ray",
))

print("IMDB:", result.external_ids.imdb)
print("Discogs release:", result.external_ids.discogs_release)
print("blu-ray.com ID:", result.external_ids.bluray_com_id)
print("dvdcompare ID:", result.external_ids.dvdcompare_id)
print("Label:", result.external_ids.extra.get("discogs_label"))
print("Catalogue:", result.external_ids.extra.get("discogs_catno"))
print("HDR format:", result.external_ids.extra.get("bluray_com_cover"))
```

Provider confidence levels (multiplied by `match_quality` for the specific
hit):

| Provider | Base confidence |
|---|---|
| `discogs` | `0.70` |
| `bluray_com` | `0.65` |
| `dvdcompare` | `0.60` |

`source_format="Blu-ray"` in `Signals` causes the `discogs` provider to try
Blu-ray format first before falling through its format chain. Without
`source_format`, the provider tries all video formats in order:
Blu-ray → DVD → VHS → Laserdisc → HD DVD → UHD Blu-ray.

See [resolve.md](resolve.md) for full consolidation and conflict detection
documentation.

## Advanced: writing a regional-edition picker

Fetch all editions from blu-ray.com, filter by region, and rank by HDR type
and bitrate:

```python
from metadatarr.client import BlurayComClient, BlurayComEdition
from typing import List, Optional
import time


_HDR_RANK = {"HDR10+": 3, "Dolby Vision": 2, "HDR10": 1}


def pick_best_edition(title: str, region: str = "B") -> Optional[BlurayComEdition]:
    """Return the highest-quality disc for *region* ('A', 'B', 'C', or 'Free')."""
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

    def _score(ed: BlurayComEdition):
        return (
            _HDR_RANK.get(ed.hdr or "", 0),
            ed.video_bitrate_kbps or 0,
        )

    return max(candidates, key=_score)


best = pick_best_edition("Dune Part Two", region="B")
if best:
    print(best.title, best.region, best.hdr, best.video_bitrate_kbps, "kbps")
```

## Scraper fragility

blu-ray.com and dvdcompare.net are HTML scrapers. The CSS selectors that
extract spec values are anchored to element IDs and class names that were
accurate when this code was written. If either site redesigns its layout,
fields will silently return `None` rather than raising.

To adapt without forking the client, subclass and override the parsing method:

```python
from typing import Optional
from bs4 import BeautifulSoup
from metadatarr.client import BlurayComClient, BlurayComEdition


class PatchedClient(BlurayComClient):
    def _parse_edition_page(
        self, soup: BeautifulSoup, bid: int, url: Optional[str]
    ) -> Optional[BlurayComEdition]:
        # Updated selectors go here.
        ...
```

`BlurayComClient._parse_edition_page` — `/metadatarr/client.py:562`
`DVDCompareClient._parse_edition_page` — `/metadatarr/client.py:762`

## Rate limits and politeness

| Source | Rate limit | Recommendation |
|---|---|---|
| blu-ray.com | None documented | `time.sleep(1)` between calls in batch jobs |
| dvdcompare.net | None documented | `time.sleep(1)` between calls in batch jobs |
| Discogs (no token) | 25 req/min | `time.sleep(2.5)` between calls |
| Discogs (with `DISCOGS_TOKEN`) | 60 req/min | `time.sleep(1)` between calls |

The Discogs API returns `429 Too Many Requests` when the limit is exceeded.
blu-ray.com and dvdcompare.net may issue temporary blocks for aggressive
scraping, but do not return a documented error code.

See [troubleshooting.md](troubleshooting.md) for empty results and debug
patterns.
