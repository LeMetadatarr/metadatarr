# metadatarr

> **One library. Every catalogue. Zero API keys.**

[![PyPI](https://img.shields.io/pypi/v/metadatarr)](https://pypi.org/project/metadatarr/)
[![Python](https://img.shields.io/pypi/pyversions/metadatarr)](https://pypi.org/project/metadatarr/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Build](https://github.com/TigreGotico/metadatarr/actions/workflows/build-tests.yml/badge.svg)](https://github.com/TigreGotico/metadatarr/actions/workflows/build-tests.yml)

Pydantic-powered Python clients and a cross-source **entity resolver** for media metadata.
Talk to the public catalogues that the *arr ecosystem, media managers, and libraries rely on —
then fuse the answers into a single, de-duplicated record with a canonical set of external IDs.

```python
from metadatarr.resolve import resolve
from mediavocab import Signals, MediaType

result = resolve(Signals(title="Inception", year=2010, medium=MediaType.MOVIE))

print(result.external_ids.tmdb_movie)   # 27205
print(result.external_ids.imdb)         # tt1375666
print(result.external_ids.wikidata)     # Q25188
```

---

## Why metadatarr?

Most media tools need to cross-reference the same work across Sonarr, MusicBrainz, Discogs,
and Wikidata — but every API has a different shape, auth model, and concept of "the same thing."
`metadatarr` handles all of that:

- **Typed clients** — every response parsed into Pydantic V2 models; no dict spelunking.
- **Keyless by default** — every built-in provider works without registration or tokens.
- **Cross-source resolver** — fans out to every relevant provider in parallel, conflict-checks
  the results, and merges winners into one `ResolveResult` with `ExternalIds`.
- **Variant fan-out** — one flag (`include_variants=True`) and the resolver collects every
  known cut, edition, or fanedit of a work.
- **Batteries-included** — pyfanedit, pymetal, tutubo, py_bandcamp, and nuvem_de_som are all
  core dependencies; no optional-extra juggling required.

---

## Installation

```bash
pip install metadatarr
```

All first-party scrapers (pyfanedit, pymetal, tutubo, py_bandcamp, nuvem_de_som) are core
dependencies — no extras required. The only optional extra is `[test]` for running the test suite.

---

## Direct clients

Each client is a thin, typed wrapper around one data source.

| Client | Source | What you get |
|---|---|---|
| `ArrMetadataClient` | Servarr proxies (Skyhook / Radarr / Lidarr) | TV shows, movies, artists — same data that powers Sonarr/Radarr/Lidarr |
| `OpenLibraryClient` | openlibrary.org | Works, editions, authors, ISBN lookup, covers |
| `BookInfoClient` | rreading-glasses (Goodreads / Hardcover) | Book metadata via Goodreads / Hardcover |
| `AnnasArchiveClient` | Anna's Archive mirrors | Book search (HTML scrape) |
| `AudioDBClient` | theaudiodb.com | Artists, albums, tracks |
| `TVmazeClient` | tvmaze.com | Shows, seasons, episodes, cast, people |
| `BlurayComClient` | blu-ray.com | Physical Blu-ray specs — audio tracks, region codes, extras |
| `DVDCompareClient` | dvdcompare.net | Regional release comparison, cut runtimes, version notes |
| `DiscogsClient` | discogs.com | Vinyl, CD, cassette releases; `search_video()` for LaserDiscs / concert VHS / music DVDs |

```python
from metadatarr import ArrMetadataClient, OpenLibraryClient, AudioDBClient, TVmazeClient

# Movies & TV via Servarr proxies
arr = ArrMetadataClient()
movie  = arr.search_movie("Alien")[0]
series = arr.search_series("The Boys")[0]
artist = arr.search_artist("Moonsorrow")[0]
print(movie.tmdb_id, series.tvdb_id, artist.mb_id)

# Books
ol  = OpenLibraryClient()
hit = ol.search("The Hobbit", limit=1)[0]
print(hit.key, hit.first_publish_year)

# Music
db  = AudioDBClient()
alb = db.search_album("Voimasta ja Kunniasta")[0]
print(alb.id_album, alb.str_genre)

# TV
tv   = TVmazeClient()
show = tv.singlesearch("Severance")
print(show.id, show.network.name)
```

---

## Cross-source resolver

When you have a title, a year, or a noisy filename and need a canonical identity across every
platform, the resolver fans out, conflict-checks, and merges:

```python
from metadatarr.resolve import resolve
from mediavocab import Signals, MediaType

# A basic lookup — metadatarr queries all active providers concurrently
result = resolve(Signals(title="OK Computer", artist="Radiohead", medium=MediaType.MUSIC))

print(result.external_ids.musicbrainz_release_group)  # MusicBrainz MBID
print(result.external_ids.wikidata)                   # Wikidata Q-id
print(result.external_ids.extra.get("bandcamp_album_id"))

# Inspect what was accepted and what was rejected
for m in result.accepted:
    print(f"  ✓ {m.provider:<20} confidence={m.confidence:.2f}")
for d in result.conflicts:
    fields = ", ".join(f"{c.signal}({c.ours}≠{c.theirs})" for c in d.fields)
    print(f"  ✗ {d.provider:<20} clashed on {fields}")
```

### Signals — tell the resolver what you know

```python
from mediavocab import Signals, MediaType

signals = Signals(
    title    = "Alien",
    year     = 1979,
    medium   = MediaType.MOVIE,
    runtime  = 6900,          # seconds — used for cut-disambiguation
    language = "en",
    country  = "US",
)
```

Pass as much or as little as you have. Every field is optional. The more context you
provide, the better providers can filter and the more aggressively conflicts are detected.

**MediaType values:** Comes from mediavocab — 18 canonical values (`MOVIE`, `EPISODIC_SERIES`, `TV`, `MUSIC`, `MUSIC_VIDEO`, `PODCAST`, `BOOK`, `COMIC`, `GAME`, `AUDIOBOOK`, `AUDIO_DRAMA`, `RADIO`, `INTERACTIVE_FICTION`, `SOUND_EFFECT`, `AMBIENT_SOUNDS`, `PLAYLIST`, `GENERIC`, `NOT_MEDIA`). See the [mediavocab spec §4.1](https://github.com/TigreGotico/mediavocab/blob/dev/docs/mediavocab_spec.md).

### Variant fan-out — editions, cuts, fanedits

```python
from metadatarr.resolve import resolve
from mediavocab import Signals, MediaType
from metadatarr.resolve.entities import EntityRole

result = resolve(Signals(
    title           = "Alien",
    year            = 1979,
    medium          = MediaType.MOVIE,
    include_variants= True,       # ← triggers second pass
))

for entity in result.variants:
    print(entity.name, entity.external_ids.fanedit_id)
    # Alien: Covenant Cut, Alien: The Director's Cut, ...
```

With `include_variants=True` the resolver runs a second pass calling `list_variants()` on
every active provider:
- **pyfanedit** — queries fanedit.org (IFDB) for fan-edited cuts of the movie
- **musicbrainz** — expands a release-group MBID to its individual releases (editions, remasters, regional pressings)

### ExternalIds — every platform in one object

```python
from mediavocab import ExternalIds

ids = result.external_ids
print(ids.tmdb_movie)                          # int
print(ids.imdb)                                # "tt0078748"
print(ids.musicbrainz_release_group)           # UUID str
print(ids.wikidata)                            # "Q103569"
print(ids.extra.get("bandcamp_album_id"))      # platform extras
```

First-class typed fields: `musicbrainz_*`, `imdb`, `tmdb_movie`, `tmdb_tv`, `tvdb`,
`isbn_10`, `isbn_13`, `olid`, `goodreads`, `wikidata`, `metal_archives_*`,
`fanedit_id`, `derived_from_imdb`, `discogs_release`, `bluray_com_id`, `dvdcompare_id`, …
plus an `extra` dict for platform-specific IDs (Bandcamp, SoundCloud, YouTube Music, …).

---

## Built-in providers

All providers are keyless. All dependencies are bundled in the core install.

Routing is **three-axis** — `media`, `modality`, and `genre_filter`. Pass `modality` on
`Signals` to route a `MediaType.GENERIC` query to audio-only or video-only providers.
See [`docs/resolve.md`](docs/resolve.md#three-axis-routing-gate) for details.

| Provider | Source | MediaType | Modality |
|---|---|---|---|
| `skyhook` | Servarr proxies | Movie, EpisodicSeries, Music, Book | universal |
| `musicbrainz` | MusicBrainz API | Music | AUDIO |
| `audiodb` | TheAudioDB | Music | AUDIO |
| `tvmaze` | TVmaze public API | EpisodicSeries | VIDEO |
| `anilist` | AniList GraphQL API | Movie, EpisodicSeries, Comic | VIDEO + TEXT |
| `jikan_anime` | Jikan (MyAnimeList) | Movie, EpisodicSeries | VIDEO |
| `jikan_manga` | Jikan (MyAnimeList) | Comic | TEXT |
| `librivox` | LibriVox API | Audiobook | AUDIO |
| `apple_podcasts` | Apple Podcasts search | Podcast, AudioDrama | AUDIO |
| `wikidata` | Wikidata API | All | universal |
| `discogs` | Discogs API | Music, MusicVideo, Generic | AUDIO + VIDEO |
| `bluray_com` | blu-ray.com scraper | Movie | VIDEO |
| `dvdcompare` | dvdcompare.net scraper | Movie | VIDEO |
| `pyfanedit` | fanedit.org / IFDB | Movie (variants) | VIDEO |
| `bandcamp` | Bandcamp | Music | AUDIO |
| `soundcloud` | SoundCloud | Music | AUDIO |
| `youtube_music` | YouTube Music | Music | AUDIO |
| `youtube` | YouTube | Video, Podcast, Generic | universal |
| `metal_archives` | Encyclopaedia Metallum | Music | AUDIO |
| `openlibrary` | OpenLibrary | Book | TEXT |
| `annas_archive` | Anna's Archive | Book | TEXT |

**YouTube vs YouTube Music** — these are intentionally separate providers.
`youtube` only emits channel IDs and refuses `MediaType.MUSIC` lookups (video IDs aren't
canonical music identities). `youtube_music` has proper entity records — stable `browseId`
values for artists and albums that are safe to treat as cross-references.

---

## Identity mappings

Some artists and labels are the same entity across platforms but no database records the link.
Declare it once in a TOML file and every resolver run picks it up automatically:

```toml
# ~/.config/metadatarr/mappings.toml

[[artist]]
name                = "Acidkid / Piratech"
soundcloud_artist_url = "https://soundcloud.com/acidkid"
bandcamp_artist_url   = "https://piratech.bandcamp.com/"

[[artist]]
name               = "Moonsorrow"
musicbrainz_artist = "6a0a7b9b-9e12-4e1c-b91d-67cedf98a6c3"
bandcamp_band_id   = "3498887240"
metal_archives_band= 27
```

The package ships a curated `metadatarr/data/mappings.toml`. Your user file at
`~/.config/metadatarr/mappings.toml` extends it — entries that share any identifier are merged,
new entries are appended. Send a PR to add publicly-verifiable cross-platform links to the
package file.

---

## Writing a custom provider

```python
from typing import Optional
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from mediavocab import ExternalIds
from mediavocab import Signals, MediaType


class MyProvider(MetadataProvider):
    name  = "my_provider"
    media = {MediaType.MUSIC}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        result = my_api.search(signals.title)
        if not result:
            return None
        return ProviderMatch(
            provider   = self.name,
            confidence = 0.7,
            signals    = Signals(title=result["title"], medium=MediaType.MUSIC),
            external_ids = ExternalIds(
                musicbrainz_artist = result.get("mbid"),
                extra = {"my_platform_id": str(result["id"])},
            ),
        )


register(MyProvider())
```

Provider guidelines:
- **Guard optional imports** — wrap `import my_lib` in `try/except ImportError`, set `self._available = False` on failure.
- **Canonical IDs only** — numeric platform IDs are stable; URL slugs are not. Store URLs as `*_url` extra keys.
- **Refuse wrong mediums** — return `None` if `signals.medium` isn't in your `media` set.
- **Confidence guide** — 0.9 for exact-ID lookups, 0.7 for strong-signal search, 0.5–0.6 for fuzzy/unreliable sources.

---

## Physical media

`BlurayComClient` and `DVDCompareClient` expose Blu-ray and DVD edition data that no
structured API covers — region codes, audio track specs, cut runtimes, regional extras:

```python
from metadatarr.resolve.providers.bluray_com import BlurayComProvider
from metadatarr.resolve.providers.dvdcompare import DVDCompareProvider
from mediavocab import Signals, MediaType

signals = Signals(title="Moon", year=2009, medium=MediaType.MOVIE)

bluray = BlurayComProvider()
match  = bluray.lookup(signals)
if match:
    print(match.external_ids.bluray_com_id)

dvd    = DVDCompareProvider()
match  = dvd.lookup(signals)
if match:
    print(match.external_ids.dvdcompare_id)
```

See [`docs/physical-disc.md`](docs/physical-disc.md) for a full walkthrough.

---

## Caching and concurrency

`resolve()` is concurrent (default 8 workers via `ThreadPoolExecutor`) and process-level cached:

```python
from metadatarr.resolve._cache import cache

cache().hits    # int — cached lookups served
cache().misses  # int — network hits
cache().clear() # force re-fetch (e.g. after adding a new provider)
```

Both hits and misses are cached, so failed lookups don't re-hit the network on retry.
Pass `resolve(signals, max_workers=N)` to tune parallelism.

---

## Documentation

| Doc | Contents |
|---|---|
| [`docs/getting-started.md`](docs/getting-started.md) | Install, first calls, common patterns |
| [`docs/models.md`](docs/models.md) | Full Pydantic model reference |
| [`docs/resolve.md`](docs/resolve.md) | Signals, providers, ResolveResult, conflict detection |
| [`docs/providers.md`](docs/providers.md) | Provider catalogue — config, optional deps, caveats |
| [`docs/recipes.md`](docs/recipes.md) | End-to-end snippets for common tasks |
| [`docs/physical-disc.md`](docs/physical-disc.md) | Blu-ray / DVD edition data |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | Gotchas and FAQ |
| [`docs/clients/`](docs/clients/) | Per-client deep dives |
| [`examples/`](examples/) | One focused script per use case |

---

## Testing

```bash
pip install -e ".[test]"
pytest
```

Tests are fully offline — all HTTP calls are stubbed with fixture files.

---

## License

MIT — see [LICENSE](LICENSE).
