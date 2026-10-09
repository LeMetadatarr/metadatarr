# metadatarr documentation

`metadatarr` is a small, Pydantic-V2-powered Python client for the public metadata
services that power the *arr stack (Sonarr, Radarr, Lidarr, Readarr-replacements)
and a handful of community book sources.

It is deliberately tiny: a single `requests`-based HTTP layer, a single
`pydantic` model layer, and one class per upstream provider.

## What's inside

| Provider | Class | Domain | Source |
|---|---|---|---|
| Sonarr Skyhook | `ArrMetadataClient.search_series` | TV (TVDB) | `skyhook.sonarr.tv` |
| Radarr Servarr API | `ArrMetadataClient.search_movie` | Movies (TMDB) | `radarrapi.servarr.com` |
| Lidarr MusicInfo | `ArrMetadataClient.search_artist` | Music (MusicBrainz) | `api.lidarr.audio` |
| rreading-glasses (Goodreads) | `BookInfoClient.goodreads()` | Books | `api.bookinfo.pro` |

| Provider | Class | Domain | Source |
|---|---|---|---|
| rreading-glasses (Hardcover) | `BookInfoClient.hardcover()` | Books | `hardcover.bookinfo.pro` |
| OpenLibrary | `OpenLibraryClient` | Books | `openlibrary.org` |
| Anna's Archive | `AnnasArchiveClient` | Books (search-by-mirror, HTML) | rotating mirrors |
| TheAudioDB | `AudioDBClient` | Music | `theaudiodb.com` |

| Provider | Class | Domain | Source |
|---|---|---|---|
| TVmaze | `TVmazeClient` | TV | `api.tvmaze.com` |
| blu-ray.com | `BlurayComClient` | Physical disc (Blu-ray / 4K UHD) | `www.blu-ray.com` (HTML scraper) |
| dvdcompare.net | `DVDCompareClient` | Physical disc (cut / version metadata) | `www.dvdcompare.net` (HTML scraper) |
| Discogs | `DiscogsClient` | Physical disc (Blu-ray / DVD / VHS / LaserDisc) + label & catalogue data | `api.discogs.com` |

Plus a cross-source **resolver** (`metadatarr.resolve`): pluggable
providers + a `Signals` / `ExternalIds` framework for fusing matches into
one canonical record. Includes a variant fan-out system: set
`signals.include_variants=True` to populate `result.variants`
with cuts / editions from `musicbrainz` (release-group → releases) and
`pyfanedit` (fanedit.org / IFDB). See [resolve.md](resolve.md) and
[providers.md](providers.md).

## Reading order

If you've never used metadatarr before, read in this order:

1. **[Getting started](getting-started.md)**: install, your first call, mental model.
2. **Pick the client(s) you need:**
   - **[ArrMetadataClient](clients/arr-metadata.md)**: TV / movies / music
   - **[BookInfoClient](clients/bookinfo.md)**: Goodreads & Hardcover via rreading-glasses
   - **[OpenLibraryClient](clients/openlibrary.md)**: OpenLibrary REST API
   - **[AnnasArchiveClient](clients/annas-archive.md)**: Anna's Archive HTML scraping
   - **[AudioDBClient](clients/audiodb.md)**: TheAudioDB artist/album/track
   - **[TVmazeClient](clients/tvmaze.md)**: TVmaze TV show/season/cast
   - **[BlurayComClient](clients/bluray-com.md)**: blu-ray.com technical specs
   - **[DVDCompareClient](clients/dvdcompare.md)**: dvdcompare.net version/cut metadata
   - **[DiscogsClient](clients/discogs.md)**: Discogs label, catalogue number, VHS, LaserDisc
2a. **[Physical disc guide](physical-disc.md)**: zero-to-hero guide covering all three physical disc sources together, version disambiguation, and the regional-edition picker.
3. **[Entity resolution](resolve.md)**: provider system, `Signals`, `ExternalIds`, entities,
   consolidation, identity mappings, and writing custom providers.
3a. **[Provider catalogue](providers.md)**: every built-in provider, its media coverage, and its caveats.
4. **[Models reference](models.md)**: every Pydantic model, every field, where it comes from.
5. **[Recipes](recipes.md)**: cross-provider workflows: ISBN-to-cover, dedup, fallback chains, async wrappers, caching.
6. **[Troubleshooting](troubleshooting.md)**: empty results, rate limiting, mirror outages, validation errors.

### Extending metadatarr (advanced)

- **[Adding a provider](add-provider.md)**: the end-to-end checklist for plugging a new source into the resolver.
- **[Testing providers](testing.md)**: the offline-fixture / mocked-HTTP pattern and the per-provider smoke contract.
- **[Contributing](../CONTRIBUTING.md)**: branch/PR flow, conventional commits → automatic versioning, running CI locally.

## Design notes (the 30-second tour)

- **Failure is silent by design.** Network errors, 5xx, malformed JSON: all collapse
  to `[]` for list endpoints or `None` for singletons. metadatarr is meant to sit in
  enrichment pipelines where one provider being down should not crash the call site.
  If you want strict mode, wrap `client._get` or subclass.
- **Casing is upstream's problem, not yours.** Servarr endpoints use camelCase,
  rreading-glasses uses PascalCase, OpenLibrary uses snake_case. The Pydantic models
  use `AliasChoices` so you always read `result.title`, never `result.Title`.
- **No auth, no keys.** Every endpoint metadatarr targets is public. If a provider
  starts requiring keys, that will be opt-in via constructor args, not a hard break.
- **Sync `requests`, on purpose.** Async is trivial to add on top
  (`asyncio.to_thread`), see the [recipes](recipes.md#async-wrapper). Forcing async
  on every consumer wasn't worth the dependency cost.
