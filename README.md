# metadatarr

Pydantic-powered Python clients and a cross-source **entity resolver** for
media metadata. One library to talk to the public catalogues that the *arr
ecosystem (Sonarr / Radarr / Lidarr) and most media tools rely on, plus a
light framework for fusing answers from many of them into a single,
de-duplicated record.

## Highlights

- **Typed direct clients** for the most useful free media databases — every
  response parsed into Pydantic V2 models.
- **Robust mapping** — handles inconsistent API shapes (casing, nesting)
  via `AliasChoices` / `AliasPath` so caller code stays clean.
- **Cross-source resolver** (`metadatarr.resolve`) — pluggable providers
  share a `Signals` bag, return `ProviderMatch` records, and the registry
  consolidates them into a merged `ResolveResult` with `ExternalIds`.
- **Variant fan-out** — set `signals.include_variants=True` and the
  resolver calls every provider's `list_variants()`, collecting
  `ProviderEntity(kind=RELEASE)` records in `result.relations[Role.RELEASE]`.
  The `pyfanedit` provider searches fanedit.org (IFDB) for movie fanedits;
  `musicbrainz` expands a release-group MBID to its individual releases.
- **Zero config, zero API keys** — every built-in provider is keyless.
  Providers that need extra packages (`pymetal`, `py_bandcamp`,
  `nuvem_de_som`, `tutubo`) silently disable themselves when the optional
  dep isn't installed.

## Installation

```bash
pip install metadatarr            # core (includes pyfanedit)
pip install metadatarr[all]       # + bandcamp, soundcloud, youtube, metal_archives
```

Optional extras: `metal_archives`, `bandcamp`, `soundcloud`, `youtube`, `test`.

## Direct clients

| Client                 | Source                                        | What it does                          |
| ---------------------- | --------------------------------------------- | ------------------------------------- |
| `ArrMetadataClient`    | Skyhook / Radarr / Lidarr Servarr proxies     | TV / movie / artist search & lookup   |
| `OpenLibraryClient`    | openlibrary.org                               | works, editions, authors, ISBN, covers |
| `BookInfoClient`       | rreading-glasses (Goodreads / Hardcover)      | book metadata via Goodreads/Hardcover |
| `AnnasArchiveClient`   | annas-archive mirrors                         | book search (HTML scrape)             |
| `AudioDBClient`        | theaudiodb.com                                | artist / album / track lookup         |
| `TVmazeClient`         | tvmaze.com                                    | show / season / cast / people lookup  |
| `BlurayComClient`      | blu-ray.com (HTML scraper)                    | physical Blu-ray edition specs, audio tracks, region, extras |
| `DVDCompareClient`     | dvdcompare.net (HTML scraper)                 | regional release comparison, cut runtimes, version notes |
| `DiscogsClient`        | api.discogs.com                               | music releases (vinyl/CD/cassette), concert film LaserDiscs/VHS, soundtrack albums; `search_video()` for video formats, `search()` for audio; `search_film()` is a deprecated alias for `search_video()` |

```python
from metadatarr import ArrMetadataClient, OpenLibraryClient, TVmazeClient

arr = ArrMetadataClient()
movie = arr.search_movie("Inception")[0]
print(movie.title, movie.tmdb_id)

ol = OpenLibraryClient()
hit = ol.search("The Hobbit", limit=1)[0]

tv = TVmazeClient()
show = tv.singlesearch("The Boys")
```

## Cross-source resolver

When you have a noisy row (a filename, a tag, a search result) and want
a canonical identity across sources:

```python
from metadatarr.resolve import Signals, Medium, active_providers, consolidate

signals = Signals(title="Inception", year=2010, medium=Medium.MOVIE)

matches = []
for provider in active_providers(medium=Medium.MOVIE):
    match = provider.lookup(signals)
    if match:
        matches.append(match)

result = consolidate(matches, local=signals)
print(result.external_ids.tmdb_movie)   # → 27205
print(result.signals.title)             # → "Inception"
```

Built-in providers: `metadatarr` (Servarr metadata-server proxy),
`musicbrainz`, `audiodb`, `tvmaze`, `wikidata`, `youtube`,
`youtube_music`, `bandcamp`, `soundcloud`, `metal_archives`, `discogs`
(music / music\_video / other), `bluray_com`, `dvdcompare`, `pyfanedit`
(variant-only; fanedit.org / IFDB). Every provider is keyless; the
optional-dep ones self-disable when the package isn't installed.

## Documentation

- [`docs/getting-started.md`](docs/getting-started.md) — install + first calls
- [`docs/models.md`](docs/models.md) — Pydantic model reference
- [`docs/resolve.md`](docs/resolve.md) — `Signals`, providers, `ResolveResult`
- [`docs/providers.md`](docs/providers.md) — provider catalogue (config, deps)
- [`docs/recipes.md`](docs/recipes.md) — common end-to-end snippets
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — gotchas
- [`docs/clients/`](docs/clients/) — per-client deep dives

## Examples

See [`examples/`](examples/) — one focused script per client family plus a
resolve walkthrough.

## Testing

```bash
pip install -e .[test]
pytest
```

Tests are fully offline (no network) — HTTP calls are stubbed.

## License

MIT — see [LICENSE](LICENSE).
