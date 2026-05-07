# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Resolver-layer overhaul, ahead of the first public release. No deletions
from the published API surface — every change is additive — but the
out-of-scope `arr_*` provider family was removed before it ever shipped.

### Routing

- **Three-axis provider gate** `(media, modality, genre_filter)`. Every
  provider now declares `modality: Set[PlaybackModality]` as a ClassVar
  (mediavocab spec axiom 13) alongside the existing `media` and
  `genre_filter` axes. `MetadataProvider.matches(signals)` evaluates all
  three so an audio-modality query never reaches a video-only provider
  and vice versa.
- **Provider auto-discovery.** `metadatarr.resolve.providers.__init__`
  walks its own directory and imports every submodule on first access,
  so registration is a side effect of dropping a file in. Adding a new
  provider is now a single-file change — no registry edits, no manual
  imports.
- **EntityRole split.** `EntityRole.{ALBUM, RELEASE, TRACK, CHARACTER}`
  were removed — those values described *what a thing is*, not *how it
  relates*, and belonged to `EntityKind` all along. Variant-emitting
  providers (a release with multiple editions, an album with multiple
  pressings) now return `ProviderMatch.variants: List[ProviderEntity]`,
  and `consolidate()` promotes them onto `ResolveResult.variants`.
  `ProviderEntity`'s validator now fails loud on `kind`/`role` mismatch
  rather than silently coercing.

### Providers

- **Renamed: `metadatarr` → `skyhook`.** The `ServarrProxyProvider`
  was registered under the name `metadatarr`, which collided with the
  package itself and made consumer code ambiguous. It is now registered
  as `skyhook`, matching the upstream service name (`skyhook.sonarr.tv`).
- **Lifted from media-archivist** (now first-class metadatarr
  providers): `anilist`, `jikan_anime`, `jikan_manga`, `librivox`,
  `apple_podcasts`.
- **Dropped self-hosted Arr providers** (`arr_sonarr` / `arr_radarr` /
  `arr_lidarr` / `arr_readarr`); the keyless `skyhook` provider covers
  the same data without setup, so the self-hosted middle man and its
  required env vars added clutter for no gain.
- **Re-registered**: `openlibrary` and `annas_archive`. Both providers
  had been *defined* for weeks but were never imported by the registry,
  so they silently never ran. Auto-discovery now picks them up.
- **Removed: `tmdb`.** Required a user-supplied API key, which violates
  metadatarr's zero-setup contract (every shipped provider must work
  out of the box without configuration).
- **Removed: `google_books`.** Anonymous quota proved too unreliable in
  practice; failures were the common case rather than the exception.

### Bug fixes

- **`librivox`** was always failing on real queries: the base URL was
  missing its trailing slash, and combined `author + title` searches
  hit an upstream quirk. Both fixed; the provider now returns matches
  for the queries the rest of the resolver actually issues.
- **`openlibrary` / `annas_archive`** were constructing
  `Signals(content_type="book")`, which `Signals` (with
  `extra="forbid"`) rejected at validation time. Removed — these
  providers are book-scoped by their `media` declaration already.

### Examples

- **`examples/learn/`** — a 9-step zero-to-hero curriculum walking new
  users from a single client call through `Signals`, registry
  discovery, `resolve()`, multi-provider consolidation, variants,
  sidecar persistence, mappings, and end-to-end enrichment. Each step
  is runnable standalone.

### Workspace consolidation

- **First-party scrapers are now hard runtime deps**, not optional
  extras. Installing metadatarr pulls in `pyfanedit`, `pymetal`,
  `tutubo`, `py_bandcamp`, and `nuvem_de_som` so every provider works
  out of the box. The `metal_archives` / `bandcamp` / `soundcloud`
  extras were dropped — only `test` remains.
- **Generic resolver providers lifted from media-archivist**: `anilist`,
  `jikan_anime`, `jikan_manga`, `google_books`, `librivox`,
  `apple_podcasts`, `tmdb` now live under `metadatarr.resolve.providers`.
  Each registers automatically on import; routing uses the new two-axis
  `(media, genre_filter)` gate so anime/manga providers select on
  `content_genres=["anime"]`/`["manga"]` rather than a fake
  `MediaType.ANIME` (anime is genre, not type — mediavocab spec
  axiom 2).
- `MetadataProvider.matches(signals)` helper centralises the routing
  test. `genre_filter: Set[str]` joins `media: Set[MediaType]` as a
  ClassVar.
- `Signals.content_genres: List[str]` — mirrors mediavocab's genre
  list convention; merged as a union by `merged()`.
- `EntityKind` extended with `VOICE_ACTOR`, `STUDIO`, `CHARACTER` for
  anime / film provider output. Each value gains
  `to_mediavocab_kind()` and `to_mediavocab_role()` bridges so callers
  building canonical `mediavocab.Entity` / `Credit` records have a
  one-line conversion. The bridges document the dual-purpose nature
  of the resolver-internal enum (mixes structural kinds, relational
  roles, and Work-shaped sub-types).
- `ExternalIds` extended with anime/manga/games/podcast/trakt/google_books
  fields previously private to media-archivist.

### Removed (duplication collapse)

- The pre-release `MetadatarrXxxxProvider` wrapper family in
  media-archivist's `providers/metadatarr.py` is unnecessary now that
  metadatarr's own registry covers Skyhook / OpenLibrary / Discogs /
  Blu-ray / DVDCompare directly. Consumers should depend on metadatarr
  and import from `metadatarr.resolve.providers`.

### Added

- **`signals.match_quality(local, candidate)`** — `[0.0, 1.0]` heuristic
  combining title fuzzy ratio, year agreement, and medium agreement.
  Every built-in provider now multiplies its base confidence by this
  score so a strong upstream that returned a *bad* candidate cannot
  outvote a weaker upstream that returned a *good* one.
- **`Signals.season` / `Signals.episode`** for disambiguating TV episodes,
  plus per-medium runtime tolerances
  (`RUNTIME_TOLERANCE_BY_MEDIUM_S`: movies ±120 s, TV ±30 s, music ±3 s,
  books `0`, podcast ±30 s, other ±5 s). `compare()` and `signal_hash()`
  both consume the new fields.
- **Diacritic-folded title comparison** — `_normalize_text` runs through
  NFKD + combining-mark strip so `Café`/`cafe` and `Pokémon`/`Pokemon`
  no longer register as conflicts.
- **ISBN normalisation** — `ExternalIds` strips formatting from
  `isbn_10`/`isbn_13` and back-fills the sibling form on construction
  (978-prefixed only). New helpers exported from
  `metadatarr.resolve.external_ids`: `normalize_isbn`, `isbn10_to_13`,
  `isbn13_to_10`.
- **Multi-candidate `lookup_candidates(signals)`** on `MetadataProvider`
  (default wraps `lookup`). Built-in overrides:
  `tmdb` (top-3, search-only), `musicbrainz` (top-5),
  `wikidata` (top-3 with per-candidate entity fetch),
  `metal_archives` (top-5).
- **Concurrent + cached `resolve()`** — provider lookups now run in a
  bounded `ThreadPoolExecutor` (default 8 workers) and pass through a
  process-wide LRU keyed by `(provider, signal_hash(signals))`. **Both**
  hits and misses are cached, so failed lookups don't re-hit the network.
  Inspect/clear via `metadatarr.resolve._cache.cache()`.
- **`ResolutionConflict` + `ResolveResult.conflicts`** — per-drop
  diagnostic listing which provider clashed, against what
  (`"local"` or the anchor provider's name), and on which fields. Lets
  callers surface disagreements without re-running `compare()`.
- **Role-aware `allocate_entity_id(role=…)`** — namesakes in different
  roles (e.g. DIRECTOR vs WRITER) now allocate distinct entity ids.
  External-id-anchored entities still collapse correctly across roles.
- **Probabilistic mappings** — `MappingEntry.score` (clamped to `[0, 1]`)
  + `MappingStore.apply(min_score=…)` for gating hand-curated vs
  auto-generated entries.
- **`metadatarr.resolve.sidecar`** — atomic `save()` / `load()` (tempfile
  + `os.replace`) and `build_index()` returning an O(1) reverse-lookup
  index over `EntitySidecar` (by external id and by normalised alias).
- **First curated mapping shipped**: `Acidkid / Piratech` (SoundCloud ↔
  Bandcamp) in `data/mappings.toml`. Backed by `tests/test_mappings_toml.py`
  which proves the round-trip enrichment in both directions plus URL
  normalisation (trailing slash, host casing).
- **Examples**: `resolve_artist_merge.py` walks Iron Maiden, Mayhem,
  Daft Punk, Pink Floyd, and Burzum through MusicBrainz, Metal Archives,
  the metadata-server proxy, and Wikidata, printing per-provider
  attribution + the merged result.

### Changed

- **`consolidate()` is now confidence-ordered.** Matches are sorted by
  `confidence` descending before iterating, so the strongest provider
  anchors the consensus regardless of input order.
- **`ExternalIds.merge()` is now first-writer-wins for `extra`** as well
  as first-class fields. Combined with the confidence ordering, the
  highest-confidence provider's IDs anchor the merged record.
- **`ExternalIds.metal_archives_song`** changed from `Optional[int]` to
  `Optional[str]` — pymetal's search-layer `song_id` is the alphanumeric
  lyrics-widget id, not an integer.
- **pymetal optional-dependency pin** raised to `>= 1.0.0a1`. The new
  flat `SongSearchHit` shape is required.

### Fixed

- **`metal_archives` provider** was reading nested
  `top.band` / `top.release` / `top.song` attributes that don't exist on
  pymetal 1.x's flat `SongSearchHit`. Result: every Metal Archives match
  returned `external_ids={}`. Rewrote to read `band_id`, `band_name`,
  `release_id`, `release_title`, `song_id` directly.
- **Upstream `pymetal/locators.py:RE_LYRIC_ID`** — non-anchored greedy
  pattern captured the single char `'n'` for every song. Filed as
  [TigreGotico/pymetal#4](https://github.com/TigreGotico/pymetal/pull/4)
  with a regression test.
- **Pydantic v1 `@validator` warnings** in `models.py:262/294/333`
  migrated to `@field_validator(mode="before")`.

### Removed

- **`metadatarr.resolve.providers.arr`** — the four self-hosted Arr
  providers that hit user-hosted *arr **app** APIs. metadatarr's scope is
  metadata-server proxies (`skyhook.sonarr.tv`, `radarrapi.servarr.com`,
  `api.lidarr.audio`); those are wrapped by the `skyhook` provider via
  `ArrMetadataClient`. Pre-release deletion — never shipped.

### Tests

- Coverage gate raised to 85 %; current run is 95.35 % over 131 tests.
- New offline suites: `test_signals` (transliteration, season/episode,
  per-medium runtime, `match_quality`), `test_isbn`, `test_entities`
  (role-aware allocation, mapping store, score gating), `test_sidecar`
  (atomic JSON, reverse index), `test_cache_and_resolve` (LRU hit/miss,
  concurrency, multi-candidate fan-out), `test_provider_candidates`
  (TMDB / MusicBrainz / Wikidata top-N), `test_mappings_toml` (the
  Acidkid/Piratech round-trip).

## [0.1.0] — 2026-04-30

First public release (initial scaffolding — superseded by the
`[Unreleased]` resolver overhaul above before tagging).

### Added
- **Direct API clients** with Pydantic V2 models:
  - `ArrMetadataClient` — Servarr metadata proxies (Skyhook for Sonarr, Radarr, Lidarr).
  - `OpenLibraryClient` — works, editions, authors, ISBN lookup, cover URLs.
  - `BookInfoClient` — rreading-glasses proxies (Goodreads / Hardcover).
  - `AnnasArchiveClient` — Anna's Archive search across mirrors.
  - `AudioDBClient` — TheAudioDB artist / album / track lookup.
  - `TVmazeClient` — TVmaze show / season / cast / people lookup.
- **Resolve framework** (`metadatarr.resolve`):
  - `Signals` / `Medium` / `compare` / `merged` for disambiguation.
  - `ExternalIds`, `EntityRecord`, `EntitySidecar`, `ProviderEntity` for
    cross-source identity.
  - `MetadataProvider` ABC + process-global registry (`register`,
    `all_providers`, `active_providers`, `consolidate`, `resolve`).
  - Built-in providers: servarr_proxy, musicbrainz, audiodb, tmdb,
    tvmaze, wikidata, youtube, youtube_music, bandcamp, soundcloud,
    metal_archives.
- Offline test suite, runnable with `pytest`.
- Examples covering each client family and a resolve walkthrough.
