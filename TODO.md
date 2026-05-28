# metadatarr — Production Roadmap

Phased checklist for a coding agent. Work top-to-bottom. Run `python -m pytest tests/ -q --tb=short && ruff check metadatarr/` after every phase.

---

## Phase 0 — Commit working-tree cleanup (prerequisite)

> The working tree has ~86 modified files representing a coherent cleanup pass: Stream/StreamPlatform model removal, Discogs nested types simplified to raw dicts, centralised user-agent, list-comprehension refactors, test dir rename. Commit all before touching anything else.

- [ ] Stage all modified files under `metadatarr/` and commit with message `refactor: remove stream models, simplify discogs types, centralise user-agent`
- [ ] Open PR from current branch → `dev` (do **not** push to `master`)
- [ ] Verify CI passes: build-tests.yml (Python 3.10–3.14) and coverage.yml (≥ 85%)

---

## Phase 1 — Bug Fixes

### C1 — `BlurayComClient.get_edition()` always returns `url=None`
- **File**: `metadatarr/client.py`
- [ ] Find where `BlurayComClient.get_edition()` builds its return value
- [ ] Replace any reference to `session.url` or `requests.Session.url` with the `Response` object's `.url` attribute (e.g. `resp.url`) to capture the final URL after redirects
- [ ] **Acceptance**: in `tests/test_physical_clients.py`, add an assertion that `edition.url is not None` on a fixture-driven parse

### H1 — Silent exception swallowing in `ArrMetadataClient._get()`
- **File**: `metadatarr/client.py`
- [ ] Locate the `except` block in `ArrMetadataClient._get()`
- [ ] Add `LOG.warning("ArrMetadataClient._get failed %s %s: %s", method, url, e)` before returning `None`
- [ ] **Acceptance**: new test in `tests/test_clients.py` — mock `requests.Session.request` to raise `requests.RequestException`, assert `caplog` contains the warning text

### H4 — MusicBrainz User-Agent header mismatch
- **File**: `metadatarr/resolve/providers/musicbrainz.py`
- [ ] Find where the `User-Agent` header is constructed (currently `TigreGotico/metadatarr`)
- [ ] Import `__version__` from `metadatarr.version`
- [ ] Replace header value with `f"JarbasAl/metadatarr/{__version__} (https://github.com/JarbasAl/metadatarr)"`
- [ ] **Acceptance**: new test — mock HTTP, assert `User-Agent` header matches the new format

### M6 — `_package_mappings_path()` accesses path outside context manager
- **File**: `metadatarr/resolve/mappings.py`
- [ ] Find `_package_mappings_path()` — it currently uses `importlib.resources.path()` as a context manager but returns the path object for use outside the `with` block
- [ ] Replace with `importlib.resources.files("metadatarr").joinpath("data/mappings.toml")` (Python ≥ 3.9, returns a `Traversable`, no context manager needed)
- [ ] **Acceptance**: `tests/test_mappings_toml.py` — assert package mappings load cleanly; run in a subprocess with `python -c "from metadatarr.resolve.mappings import MappingStore; MappingStore()"` to confirm no error

### M1 — Duplicate genre fallback block in `BlurayComClient`
- **File**: `metadatarr/client.py` (around lines 748–758 pre-cleanup)
- [ ] Find the duplicated genre fallback block and remove the second copy
- [ ] **Acceptance**: all existing `test_physical_clients.py` tests still pass

### M2 — `LidarrArtist` inherits meaningless `title` field
- **File**: `metadatarr/models.py`
- [ ] Add `@property` override in `LidarrArtist`: `def title(self) -> str: return self.name`
- [ ] **Acceptance**: `assert LidarrArtist(name="Iron Maiden").title == "Iron Maiden"` — add this as a test case in `tests/test_models.py`

---

## Phase 2 — Test Coverage Gaps

### H2 — `_http_cache.py` only 26% covered
- **Files**: `metadatarr/resolve/_http_cache.py`, `tests/test_http_cache.py` (new)
- [ ] Create `tests/test_http_cache.py`
- [ ] `test_setup_and_hit`: enable cache via `monkeypatch.setenv("METADATARR_HTTP_CACHE", str(tmp_path))`, call `setup()`, make two identical GET requests through a mocked `requests.Session.send`, assert the second call does **not** hit the mock (served from cache)
- [ ] `test_ttl_zero_never_caches`: set `METADATARR_HTTP_CACHE_TTL=0` with a very old cache file mtime, assert cached response is not returned
- [ ] `test_clear`: populate cache dir with dummy files, call `clear()`, assert dir is empty
- [ ] `test_info_keys`: after `setup()`, call `info()`, assert result is a dict containing at least `enabled`, `directory`, `ttl`
- [ ] `test_env_disabled`: with `METADATARR_HTTP_CACHE` unset, assert `setup()` is a no-op (mock not patched)
- [ ] **Acceptance**: `pytest tests/test_http_cache.py -v` all pass; coverage for `_http_cache.py` reaches ≥ 80%

### H3 — `AnnasArchiveClient` has no fixture tests; parser uses positional column indices
- **Files**: `metadatarr/client.py`, `tests/fixtures/annas_archive_search.html` (new), `tests/test_physical_clients.py`
- [ ] Capture a representative Anna's Archive search result HTML page and save it to `tests/fixtures/annas_archive_search.html` (minimal anonymised fixture is fine — include at least one result row with title, author, md5, format)
- [ ] In `AnnasArchiveClient`, replace any `row.find_all("td")[N]` column-index selectors with CSS class or `data-*` attribute selectors so that adding/removing columns doesn't break parsing
- [ ] Add `test_annas_archive_fixture` in `tests/test_physical_clients.py`: load the fixture HTML, pass it to the parser, assert `results[0].title`, `results[0].author`, `results[0].md5` are non-empty strings
- [ ] **Acceptance**: `pytest tests/test_physical_clients.py::test_annas_archive_fixture -v` passes

---

## Phase 3 — Architecture / Design Issues

### M3 — `import time` inside `DiscogsClient._get()` method body
- **File**: `metadatarr/client.py`
- [ ] Move `import time` to module-level imports
- [ ] **Acceptance**: `ruff check metadatarr/client.py` clean; all tests pass

### M4 — `consolidate()` calls `apply_mappings()` for all 14 EntityKind values per match
- **Files**: `metadatarr/resolve/base.py`, `metadatarr/resolve/mappings.py`
- [ ] In `consolidate()`, find the loop that calls `apply_mappings()` across all EntityKind values
- [ ] Replace with: only call `apply_mappings(role, external_ids)` for roles that actually appear in `match.relations`
- [ ] **Acceptance**: write a microbenchmark (or add a timing assert) in `tests/test_cache_and_resolve.py` showing consolidation of a 3-provider result completes in < 5 ms; all existing tests still pass

### M5 — `pyfanedit` is a hard dependency but only used by one optional provider
- **File**: `pyproject.toml`, `metadatarr/resolve/providers/pyfanedit.py`
- [ ] Move `pyfanedit` from `[project.dependencies]` to `[project.optional-dependencies]` under key `fanedits`
- [ ] The provider already catches `ImportError` via `is_available()` — no code change needed in the provider
- [ ] Update the install snippet in `README.md`: add `pip install metadatarr[fanedits]` for fanedit support
- [ ] **Acceptance**: `pip install -e . --no-deps` (without pyfanedit installed) → `python -c "from metadatarr.resolve import active_providers; print(active_providers())"` succeeds without ImportError; `tests/test_providers_registry.py` passes

### M7 — `include_variants` control flag pollutes `Signals` data model
- **Files**: `metadatarr/resolve/base.py`, all call sites in `examples/`, `tests/`
- [ ] Add `@dataclass class ResolveOptions: include_variants: bool = False; max_workers: int = 8` in `metadatarr/resolve/base.py`
- [ ] Change `resolve()` signature to `resolve(signals, options: ResolveOptions | None = None, *, include_variants: bool | None = None, max_workers: int | None = None)` — old kwargs still work but log a `DeprecationWarning` if used
- [ ] Export `ResolveOptions` from `metadatarr/resolve/__init__.py`
- [ ] Update all `examples/` scripts that pass `include_variants=True` to use `options=ResolveOptions(include_variants=True)`
- [ ] **Acceptance**: `pytest tests/ -q` passes; `from metadatarr.resolve import ResolveOptions` works

### M8 — `ExternalIds.extra` typed `Dict[str, str]` but semantically stores mixed types
- **Action**: determine ownership first
- [ ] Check whether `ExternalIds` is defined in `mediavocab` (upstream) or locally in `metadatarr/resolve/`
- [ ] **If local**: change `extra: Dict[str, str]` → `extra: Dict[str, Any]` and add `from typing import Any` import; add a note in `docs/resolve.md` documenting key naming conventions (`"cover_url"`, `"feed_url"`, etc.)
- [ ] **If upstream (mediavocab)**: open an issue at the mediavocab repo; add `# TODO: upstream ExternalIds.extra should be Dict[str, Any]` comment in the relevant provider files; document current workaround in `docs/resolve.md`
- [ ] **Acceptance**: no `mypy` / `ruff` type errors in files that write to `extra`

---

## Phase 4 — Provider Hardening

### Rate-limit compliance: MusicBrainz (1 req/s)
- **File**: `metadatarr/resolve/providers/musicbrainz.py`
- [ ] Add a module-level `_last_req: float = 0.0` timestamp
- [ ] Before each HTTP call, compute elapsed = `time.monotonic() - _last_req`; if `elapsed < 1.0`: `time.sleep(1.0 - elapsed)`; update `_last_req = time.monotonic()`
- [ ] **Acceptance**: new test — mock `time.sleep`, make two consecutive `lookup()` calls, assert `time.sleep` was called with a value ≤ 1.0

### Rate-limit compliance: Jikan (3 req/s)
- **File**: `metadatarr/resolve/providers/jikan.py`
- [ ] Same pattern as MusicBrainz but with 0.34 s minimum gap
- [ ] **Acceptance**: same mock-sleep test pattern

### Retry on transient HTTP errors (all clients)
- **File**: `metadatarr/client.py`
- [ ] In the base `_get()` method (or `__init__` where `requests.Session` is created), mount a `urllib3.util.retry.Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])` adapter
- [ ] Use `session.mount("https://", HTTPAdapter(max_retries=retry))` and `session.mount("http://", ...)`
- [ ] **Acceptance**: `tests/test_clients.py` — mock a 503 followed by a 200, assert the client returns the 200 response

### Discogs optional authentication
- **Files**: `metadatarr/resolve/providers/discogs.py`, `metadatarr/client.py` (`DiscogsClient`)
- [ ] In `DiscogsClient.__init__()`, read `os.environ.get("DISCOGS_TOKEN")`
- [ ] If token present: add header `Authorization: Discogs token={token}` to all requests
- [ ] If absent: log `LOG.info("Discogs running unauthenticated (25 req/min limit)")` once on init
- [ ] **Acceptance**: `monkeypatch.setenv("DISCOGS_TOKEN", "fake")` → assert `Authorization` header present in mocked request

### Wikidata SPARQL fallback in `enrich()`
- **File**: `metadatarr/resolve/providers/wikidata.py`
- [ ] In `WikidataProvider.enrich(external_ids)`, after the existing `wbgetentities` path, add a SPARQL fallback for when the Q-id is not directly known but an IMDb/TMDB/MBID value is available
- [ ] SPARQL endpoint: `https://query.wikidata.org/sparql` with `Accept: application/sparql-results+json`
- [ ] Example query: `SELECT ?item WHERE { ?item wdt:P345 "tt1234567" }` (IMDb P345)
- [ ] Map each `ExternalIds` field to its Wikidata property ID (P345=IMDb, P4947=TMDB movie, P4983=TMDB TV, P434=MusicBrainz artist)
- [ ] **Acceptance**: existing tests pass; new test with fixture JSON response from SPARQL confirms Q-id is extracted correctly

---

## Phase 5 — New Providers

> Each provider: file in `metadatarr/resolve/providers/<name>.py`, declares `name`/`media`/`playback_type` class vars, implements `lookup()` + `is_available()`, self-registers at module bottom, has ≥ 1 fixture-based test.

### `tmdb.py` — The Movie Database
- [ ] Create `metadatarr/resolve/providers/tmdb.py`
- [ ] `is_available()`: return `bool(os.environ.get("TMDB_API_KEY"))`
- [ ] `media = {MediaType.MOVIE, MediaType.TV_SHOW}`
- [ ] `lookup(signals)`: call `https://api.themoviedb.org/3/search/movie` or `/search/tv` based on `signals.media`; return top hit as `ProviderMatch` with confidence derived from title similarity
- [ ] `enrich(external_ids)`: fetch by TMDB ID → extract cast, crew, genres, runtime
- [ ] `list_variants(external_ids, signals)`: fetch `/movie/{id}/release_dates` → emit `ProviderEntity` per regional cut
- [ ] Add fixture `tests/fixtures/tmdb_search_movie.json` and test in `tests/test_providers_registry.py`

### `imdb.py` — IMDb (via `cinemagoer`)
- [ ] Create `metadatarr/resolve/providers/imdb.py`
- [ ] `is_available()`: try `import imdb; return True` except ImportError → False
- [ ] Add `cinemagoer` to `[project.optional-dependencies]` under `imdb`
- [ ] `media = {MediaType.MOVIE, MediaType.TV_SHOW}`
- [ ] `lookup(signals)`: search by title+year, return top match
- [ ] `enrich(external_ids)`: fetch by IMDb ID, return cast/director/writer entities
- [ ] Add fixture test

### `goodreads.py` — Goodreads (via existing `BookInfoClient`)
- [ ] Create `metadatarr/resolve/providers/goodreads.py`
- [ ] Wrap `BookInfoClient.goodreads()` — no new HTTP code needed
- [ ] `media = {MediaType.BOOK}`
- [ ] `lookup(signals)`: `client.search(signals.title)` → pick best match by title fuzzy score
- [ ] `enrich(external_ids)`: `client.get_work(goodreads_id)` → extract author entities, series name, genres
- [ ] Add fixture test

### `spotify.py` — Spotify
- [ ] Create `metadatarr/resolve/providers/spotify.py`
- [ ] `is_available()`: return bool of both `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` env vars
- [ ] Use Client Credentials OAuth flow (`https://accounts.spotify.com/api/token`) to get bearer token; cache token until expiry
- [ ] `media = {MediaType.MUSIC}`
- [ ] `lookup(signals)`: `GET /v1/search?q=...&type=track`; return top track with artist, album, Spotify URI
- [ ] `enrich(external_ids)`: `GET /v1/artists/{id}` → extract `external_urls.musicbrainz` if present (not always), genres, followers
- [ ] Add fixture test (mock the OAuth token endpoint + search endpoint)

### `apple_music.py` — Apple Music (iTunes Search API, no key)
- [ ] Create `metadatarr/resolve/providers/apple_music.py`
- [ ] `is_available()`: always True (no auth required)
- [ ] `media = {MediaType.MUSIC, MediaType.PODCAST}`
- [ ] Reuse the same `https://itunes.apple.com/search` endpoint pattern already used in `podcast_index.py`
- [ ] `lookup(signals)`: search with `media=music` or `media=podcast` depending on `signals.media`
- [ ] Add fixture test

---

## Phase 6 — Mappings Expansion

- **File**: `metadatarr/data/mappings.toml`
- [ ] Add 10 `[[artist]]` mapping entries for well-known artists where MBID ↔ Discogs ↔ Bandcamp ↔ SoundCloud IDs diverge (examples: Daft Punk, Boards of Canada, Aphex Twin, Nine Inch Nails, Portishead, Massive Attack, Radiohead, Chemical Brothers, Underworld, Prodigy)
- [ ] Add 5 `[[podcast]]` mapping entries linking Apple Podcasts collection ID ↔ Podcast Index feed ID for major shows
- [ ] Ensure each entry has `score = 1.0` (manually verified), `mbid`, and at least one platform ID
- [ ] Document the full TOML schema (all supported section types and key names) in a new section of `docs/resolve.md` — "Mappings file format"
- [ ] **Acceptance**: `pytest tests/test_mappings_toml.py -v` passes with all new entries loaded

---

## Phase 7 — Docs & Examples

### docs/providers.md
- [ ] Reconcile provider count in the table header/intro with actual count (21 active providers)
- [ ] Add **Rate limit** column: e.g. MusicBrainz "1 req/s", Jikan "3 req/s / 60 req/min", Discogs "25/min unauth, 60/min auth", Wikidata "no hard limit"
- [ ] Add **Auth** column: "None" or env var name (e.g. `DISCOGS_TOKEN`, `TMDB_API_KEY`, `SPOTIFY_CLIENT_ID`)

### docs/resolve.md
- [ ] Add `ResolveOptions` documentation section (after M7 is complete): fields, defaults, example usage
- [ ] Add `ExternalIds.extra` key naming convention section (after M8 is complete)
- [ ] Cross-link to providers.md "Writing a custom provider" section

### examples/ hygiene
- [ ] Check `examples/vhs_legacy_live_test.py` and `examples/vhs_legacy_to_physical.py` — verify they don't import removed `Stream`/`StreamPlatform` classes; fix imports if broken
- [ ] Check `examples/learn/` directory exists; if not, create it with the 9-step curriculum scripts referenced in `docs/README.md`
- [ ] Run `python -m py_compile examples/*.py examples/**/*.py` — all must pass

---

## Phase 8 — Packaging & Release

### pyproject.toml audit
- [ ] Verify `[project.urls]` `Homepage` points to `https://github.com/JarbasAl/metadatarr`
- [ ] Ensure `[project.optional-dependencies]` has: `test = ["pytest>=7"]`, `fanedits = ["pyfanedit"]` (after M5), `imdb = ["cinemagoer"]` (after Phase 5 imdb.py)
- [ ] Add floor-version pins for all hard deps if missing; no upper-bound pins unless a specific breakage is known
- [ ] Remove any stale extras (e.g. `metal_archives`, `bandcamp`, `soundcloud` if they were extras before consolidation)

### Pre-release checklist
- [ ] All C/H/M audit items above are checked off
- [ ] `python -m pytest tests/ -q --tb=short` passes with zero failures, zero errors
- [ ] Coverage report shows ≥ 90% (`pytest --cov=metadatarr --cov-report=term-missing`)
- [ ] `ruff check metadatarr/` — zero violations
- [ ] `pip-audit` (or `pip audit`) — zero known CVEs in dependency tree
- [ ] Import smoke-test: `python -c "from metadatarr import resolve; from metadatarr.resolve import Signals, MediaType, active_providers; print(len(active_providers()), 'providers active')"`
- [ ] All example scripts compile: `python -m py_compile examples/*.py`
- [ ] Matrix test: confirm `build-tests.yml` green on Python 3.9, 3.10, 3.11, 3.12, 3.13

### Version bump to 0.1.0 stable
- [ ] **Do NOT edit `version.py` manually** — gh-automations bumps versions from conventional commit prefixes
- [ ] Merge `dev` → `master` to trigger `release_workflow.yml` (alpha PyPI publish + PR to stable)
- [ ] Approve and merge the auto-generated stable PR once CI is green
- [ ] Verify PyPI package installs correctly: `pip install metadatarr==0.1.0` in a fresh venv

---

## Verification Commands

```bash
# After every phase:
cd metadatarr
python -m pytest tests/ -q --tb=short
ruff check metadatarr/

# Full pre-release check:
python -m pytest tests/ --cov=metadatarr --cov-report=term-missing -q
pip-audit
python -m py_compile examples/*.py

# Smoke-test (no network):
python -c "
from metadatarr import resolve
from metadatarr.resolve import Signals, MediaType
s = Signals(title='Test', media=MediaType.MUSIC)
providers = resolve.active_providers()
print(len(providers), 'providers active')
"
```

---

## Phase 9 — New Repo Integrations

> These repos all live as sibling directories in the same workspace (`../` relative to `metadatarr/`). Each section below defines a new provider file to create inside `metadatarr/metadatarr/resolve/providers/`. The provider auto-loads via the existing `_autoload()` mechanism — no edits to `__init__.py` needed. Add each library to `[project.optional-dependencies]` in `pyproject.toml`, not to hard deps, so the package installs cleanly without them.
>
> Pattern for each provider:
> - `is_available()` — guard with a try-import of the optional library
> - `lookup(signals)` — call the library's search/browse, pick the best hit, return a `ProviderMatch`
> - `enrich(external_ids)` — fetch full detail by ID, populate `ExternalIds` and `relations`
> - `list_variants()` — only if the source has meaningful edition/format variants; otherwise omit
> - One fixture-based test in `tests/test_providers_<name>.py`
> - Add the optional dep to `pyproject.toml` under the appropriate extras key

---

### P9.0 — Prerequisites: upstream library gaps and mediavocab additions

Before writing any provider, two upstream issues must be resolved. Block P9.1–P9.5 on these.

#### P9.0b — Add adult-content ExternalIds fields to `mediavocab`

`mediavocab/mediavocab/models/external_ids.py` already has `IAFD` and `ADULTFILMDATABASE` as string constants but the `ExternalIds` pydantic model needs first-class fields for Pornhub and FreeOnes so IDs survive merging and serialisation. Hanime's slug goes in `extra` (niche enough).

Changes needed in `mediavocab` repo (`../mediavocab/`):

- [ ] Add to the constants block:
  ```python
  PORNHUB = "pornhub"      # pornhub model/pornstar slug
  FREEONES = "freeones"    # freeones performer slug
  ```
- [ ] Add typed fields to the `ExternalIds` pydantic model:
  ```python
  pornhub: Optional[str] = None
  freeones: Optional[str] = None
  ```
- [ ] Add both to `ALL_KNOWN_KEYS` and `KNOWN_EXTERNAL_IDS`
- [ ] Bump `mediavocab` version via a conventional commit so metadatarr can pin the new release

#### P9.0c — Add public API module to `pyfreeones`

`pyfreeones` has no `__init__.py` and no `performer.py`. The parse/transport/model layers are complete but nothing ties them into a callable public API. Required additions in the `../pyfreeones/` repo:

- [ ] Create `pyfreeones/performer.py`:
  ```python
  def get_performer(slug: str) -> Performer:
      html = get_html(f"/{slug}/bio")
      raw = parse_bio_page(html, slug)
      return Performer(stats=PhysicalStats(**raw.pop("stats")), social=SocialLinks(**raw.pop("social")), **raw)

  def find_performer(name: str) -> Optional[Performer]:
      results = search_performers(name)
      name_lower = name.lower()
      for r in results:
          if r.name.lower() == name_lower:
              return r.get()
      return results[0].get() if results else None
  ```
- [ ] Create a `search_performers(query: str) -> List[SearchResult]` function (in `performer.py` or a new `search.py`):
  ```python
  def search_performers(query: str) -> List[SearchResult]:
      from urllib.parse import quote_plus
      html = get_html(f"/performers?q={quote_plus(query)}")
      return [SearchResult(slug=s, name=n, url=u, photo_url=p)
              for s, n, u, p in parse_search_results(html)]
  ```
- [ ] Create `pyfreeones/__init__.py` exposing: `search_performers`, `get_performer`, `find_performer`, `Performer`, `SearchResult`, `PhysicalStats`, `SocialLinks`
- [ ] Note: `SearchResult.get()` in `models.py` already calls `from pyfreeones.performer import get_performer` — once `performer.py` exists this will work

---

### P9.1 — `tunein.py` — TuneIn radio station lookup

**Upstream**: `../tunein/tunein/` (package `tunein`)
**Optional dep key**: `radio`
**MediaType**: `MediaType.RADIO`

The `tunein` library wraps TuneIn's `Describe.ashx` and browse APIs. No auth required. The package has `tunein/__init__.py`, `tunein/parse.py` (with `fuzzy_match`), and `tunein/transport.py`. Read `tunein/__init__.py` to verify the exact function signatures before implementing — the describe/search APIs return station dicts with `GuideId`, `Text`, and stream `URL` fields.

**ExternalIds fields to populate**:
- `external_ids.tunein` — the `GuideId` string (e.g. `"s12345"`)
- `external_ids.extra["stream_url"]` — first playable stream URL from the describe response
- `external_ids.extra["bitrate"]` — bitrate int if present in describe response
- `external_ids.extra["reliability"]` — reliability int (0–100) if present

**Lookup logic**:
- `signals.title` → `tunein.search(signals.title)` → pick station using `tunein.parse.fuzzy_match` or `difflib.SequenceMatcher`
- `signals.medium` guard: skip unless `signals.medium in {MediaType.RADIO, None}`

**Enrich logic**:
- Read `external_ids.tunein` → call `tunein.describe(guide_id)` → populate the extra fields above

**Test file**: `tests/test_providers_tunein.py`
- Fixture: `tests/fixtures/tunein_describe.json` — representative describe response dict
- `test_tunein_enrich_fixture`: inject fixture via monkeypatch, assert `external_ids.tunein` and `extra["stream_url"]` non-empty
- `test_tunein_unavailable`: mock ImportError on `tunein`, assert `is_available()` False

---

### P9.2 — `audiobooker.py` — Audiobook multi-source provider

**Upstream**: `../audiobooker/audiobooker/` (package `audiobooker`)
**Optional dep key**: `audiobooks`
**MediaType**: `MediaType.AUDIOBOOK`

The `audiobooker` library federates multiple free audiobook sources (LibriVox, Internet Archive, LoyalBooks, etc.) through a common `search()` function that returns `AudioBook` objects. There is also `converters.audiobook_to_release` that maps `AudioBook` → a mediavocab-compatible structure.

**Key public API**:
- `from audiobooker import search` — `search(title, max_results=5)` → `List[AudioBook]`
- `from audiobooker import search_by_author, search_by_title`
- `from audiobooker.converters import audiobook_to_release`
- `AudioBook` fields: `title`, `authors` (list of `BookAuthor`), `narrators` (list of `AudiobookNarrator`), `description`, `language`, `tags`, `url` (canonical page URL)

**ExternalIds fields to populate**:
- `external_ids.librivox` — from `AudioBook.librivox_id` if the source is LibriVox (check if field exists; if not, store in `extra["librivox_id"]`)
- `external_ids.extra["audiobook_url"]` — `AudioBook.url`
- `external_ids.extra["audiobook_source"]` — the source class name (e.g. `"LibriVoxBook"`)

**Relations to emit**:
- For each `BookAuthor` in `book.authors`: emit a `ProviderEntity(role=EntityRole.AUTHOR, name=author.name, external_ids=...)`
- For each `AudiobookNarrator` in `book.narrators`: emit a `ProviderEntity(role=EntityRole.NARRATOR, name=narrator.name, external_ids=...)`

**Lookup logic**:
- Use `signals.title` → `search_by_title(signals.title, max_results=5)` → pick best hit by title similarity
- If `signals.creator` (author) is set: use `search_by_author(signals.creator)` and then filter by title similarity

**Enrich logic**:
- If `external_ids.librivox` is set: call `audiobooker.scrappers.librivox.LibriVoxBook(librivox_id).get_book()` (verify exact API) to get full metadata

**Test file**: `tests/test_providers_audiobooker.py`
- Fixture: `tests/fixtures/audiobooker_search.json` — minimal list of 2 `AudioBook` dicts
- `test_audiobooker_lookup_fixture`: mock `search_by_title`, assert `ProviderMatch.external_ids.extra["audiobook_url"]` non-empty
- `test_audiobooker_relations`: assert at least one `EntityRole.AUTHOR` relation returned

---

### P9.3 — `tutubo.py` — YouTube / YouTube Music provider

**Upstream**: `../tutubo/tutubo/` (package `tutubo`)
**Optional dep key**: `youtube`
**MediaType**: `{MediaType.MUSIC, MediaType.MUSIC_VIDEO, MediaType.PODCAST}`

**Important**: check `metadatarr/resolve/providers/youtube.py` and `youtube_music.py` before writing this. If either already imports `tutubo` internally, record the finding in a comment and skip the corresponding coverage — the goal is to add tutubo's richer music-specific search where not already present.

**Key public API**:
- `from tutubo import search_yt` → `List[Video]`; `Video` fields: `videoid`, `title`, `channel_id`, `channel_name`
- `from tutubo import search_yt_music` → `List[MusicTrack | MusicAlbum | MusicArtist]`; `MusicTrack`: `videoid`, `title`, `artist`, `album`; `MusicArtist`: `channel_id`, `name`
- `from tutubo import Channel` — `Channel(channel_id)` → full channel metadata

**ExternalIds fields to populate**:
- `external_ids.youtube_video` — `video.videoid` (music/music-video matches)
- `external_ids.youtube_channel` — `video.channel_id` or `artist.channel_id`
- `external_ids.youtube_music_artist` — for `MusicArtist` matches

**Lookup logic**:
- `MUSIC` / `MUSIC_VIDEO`: `search_yt_music(f"{signals.title} {signals.creator or ''}")` → pick best `MusicTrack` by title+artist similarity
- `PODCAST`: `search_yt(signals.title)` → prefer channels whose name matches `signals.title`
- Anything else: return `None`

**Test file**: `tests/test_providers_tutubo.py`
- Fixture: `tests/fixtures/tutubo_music_search.json`
- `test_tutubo_music_lookup_fixture`: mock `search_yt_music`, assert `external_ids.youtube_video` non-empty
- `test_tutubo_unavailable`: mock ImportError, assert `is_available()` False

---

### P9.4 — `pyiafd.py` — IAFD adult film database

**Upstream**: `../pyiafd/pyiafd/` (package `pyiafd`)
**Optional dep key**: `adult`
**MediaType**: `MediaType.MOVIE` for feature films (`title.is_webscene == False`, `title.minutes` typically > 50); `MediaType.SHORT_FILM` for web scenes (`title.is_webscene == True`)

IAFD is the most structured of the adult sources — clean UUID-based IDs, full cast with per-member UUIDs, studio/distributor split, cover art. It should be the anchor provider for adult title lookup; Pornhub and FreeOnes enrich on top.

**Key public API** (all confirmed by reading source):
- `from pyiafd import search_titles` → `List[SearchResult]`; each `SearchResult` has `id` (UUID str), `name`, `year`
- `from pyiafd import get_title` — `get_title(uuid)` → `Title`
- `from pyiafd import find_title` — `find_title(name, year=None)` → `Optional[Title]`
- `Title` fields: `id` (UUID), `title`, `year`, `director`, `distributor`, `studio`, `minutes`, `release_date`, `is_all_girl`, `is_all_male`, `is_compilation`, `is_webscene`, `cover_url`, `cast: List[CastMember]`
- `CastMember` fields: `name`, `id` (UUID), `url`, `role` (industry role string e.g. `"Female"`, `"Male"`), `headshot_url`
- `Title.runtime_minutes` — property returning `Optional[int]`

**ExternalIds fields to populate**:
- `external_ids.iafd` — `title.id` (UUID string)
- `external_ids.extra["iafd_url"]` — `title.url`
- `external_ids.extra["iafd_studio"]` — `title.studio`
- `external_ids.extra["iafd_distributor"]` — `title.distributor` (may differ from studio)
- `external_ids.extra["iafd_cover_url"]` — `title.cover_url`

**Relations to emit**:
- `title.director` (non-empty) → `ProviderEntity(role=EntityRole.DIRECTOR, name=title.director)`
- Each `CastMember` → `ProviderEntity(role=EntityRole.ACTOR, name=cast.name, external_ids=ExternalIds(iafd=cast.id, extra={"iafd_url": cast.url, "iafd_role": cast.role}))`

**Signals to populate on the match**:
- `signals.year = int(title.year)` if parseable
- `signals.runtime_seconds = title.runtime_minutes * 60` if not None

**Lookup logic**:
- `search_titles(signals.title)` → filter by year ±1 if `signals.year` set → pick best by `difflib.SequenceMatcher` ratio ≥ 0.7 → `get_title(result.id)`
- Confidence: 0.6 base; +0.2 if year matches exactly; +0.15 if title ratio ≥ 0.95

**Enrich logic**: `external_ids.iafd` → `get_title(external_ids.iafd)` → repopulate all fields

**Test file**: `tests/test_providers_pyiafd.py`
- Fixture: `tests/fixtures/iafd_title.json` — `Title.as_dict()` output
- `test_iafd_lookup_fixture`: mock `search_titles` and `get_title`, assert `external_ids.iafd` non-empty and `extra["iafd_studio"]` non-empty
- `test_iafd_relations`: assert `EntityRole.DIRECTOR` and ≥1 `EntityRole.ACTOR` in relations
- `test_iafd_media_type`: assert `MOVIE` for `is_webscene=False`, `SHORT_FILM` for `is_webscene=True`

---

### P9.5 — `pypornhub.py` — Pornhub video + performer metadata

**Upstream**: `../pypornhub/pypornhub/` (package `pypornhub`)
**Optional dep key**: `adult`
**MediaType**: `MediaType.SHORT_FILM`

Pornhub has no stable cross-references to IAFD — performer slugs are PH-specific. Integration value: stream URLs, PH performer slugs for cross-referencing via `ExternalIds.pornhub`, and folksonomy tags.

**Key public API** (confirmed by reading source):
- `import pypornhub as ph`
- `ph.search_videos(query, ordering="tr", page=1)` → `List[VideoItem]`; `VideoItem` fields: `video_id` (str), `vkey` (str), `title`, `url`, `duration`, `segment`
- `ph.fetch_video(vkey: str)` → `VideoMeta`; key fields: `video_id` (int), `vkey` (str), `title`, `url`, `thumbnail`, `duration_seconds` (int), `tags: List[str]`, `pornstars: List[PornstarRef]`, `streams: List[MediaStream]`, `best_stream: Optional[MediaStream]`
  - `PornstarRef` has `slug` (str), `name` (str), `.url` property
- `ph.fetch_model(slug: str)` → `ModelProfile`; `physical: PhysicalAttributes` (gender, ethnicity, hair_color, measurements, height, weight); `career: CareerInfo` (status, start); `social_links: List[SocialLink]`

**ExternalIds fields to populate**:
- `external_ids.extra["pornhub_vkey"]` — `video_meta.vkey`
- `external_ids.extra["pornhub_url"]` — `video_meta.url`
- `external_ids.extra["pornhub_stream_url"]` — `video_meta.best_stream.url` if present
- `external_ids.extra["tags"]` — `json.dumps(video_meta.tags)` — tags as JSON array string only

**Relations to emit**:
- Each `PornstarRef` → `ProviderEntity(role=EntityRole.ACTOR, name=ref.name, external_ids=ExternalIds(pornhub=ref.slug))`
  - `ExternalIds.pornhub` requires P9.0b

**Lookup logic**:
- Skip unless `signals.medium in {MediaType.SHORT_FILM, None}`
- `ph.search_videos(signals.title, ordering="tr")` → pick first with `difflib` ratio ≥ 0.6 → `ph.fetch_video(item.vkey)`
- Confidence: 0.5 base; +0.15 if ratio ≥ 0.9

**Performer profile helper** (module-level, not a provider method):
- `def get_performer_profile(slug: str) -> ModelProfile` — wraps `ph.fetch_model`, used by downstream enrichment scripts to hydrate a `ProviderEntity` that already has `external_ids.pornhub`

**Test file**: `tests/test_providers_pypornhub.py`
- Fixture: `tests/fixtures/pornhub_videometa.json` — `VideoMeta` as dict
- `test_pornhub_fetch_fixture`: mock `ph.fetch_video`, assert `extra["pornhub_vkey"]` non-empty
- `test_pornhub_performer_relations`: assert ≥1 `EntityRole.ACTOR` with `external_ids.pornhub` set
- `test_pornhub_tags_not_in_relations`: assert no `ProviderEntity` emitted for tags

---

### P9.6 — `pyfreeones.py` — FreeOnes performer profile enrichment

**Upstream**: `../pyfreeones/pyfreeones/` (package `pyfreeones`)
**Optional dep key**: `adult`

> **Performer-enrichment only — not a title-lookup provider.** FreeOnes indexes performer profiles. `lookup()` returns `None`. The provider enriches `ProviderEntity` objects that have a performer name, called by downstream enrichment scripts, not the main `resolve()` pipeline.

**Prerequisites**: P9.0c must be complete before implementing this provider.

**Key public API** (once P9.0c exists):
- `from pyfreeones import search_performers` → `List[SearchResult]`; `SearchResult` fields: `slug`, `name`, `url`, `photo_url`
- `from pyfreeones import get_performer` → `Performer`
- `Performer` fields: `slug`, `name`, `url`, `aliases: List[str]`, `date_of_birth`, `birth_year`, `place_of_birth`, `nationality`, `career_status`, `career_start`, `career_end`, `professions: List[str]`, `stats: PhysicalStats`, `photo_url`, `social: SocialLinks`
- `PhysicalStats` fields: `height_cm`, `weight_kg`, `hair_color`, `eye_color`, `ethnicity`, `boobs` ("Natural"/"Fake"), `tattoos: Optional[bool]`, `piercings: Optional[bool]`, `measurements: Measurements` (bust/waist/hip/cup)
- `SocialLinks` fields: `twitter`, `instagram`, `onlyfans`, `manyvids`, `pornhub`, `tiktok`, `fancentro`, `modelhub`, plus `other: List[str]`

**What FreeOnes uniquely offers over IAFD**:
- Social media links (OnlyFans, Twitter, Instagram, TikTok, ManyVids, FanCentro)
- Bust/waist/hip measurements and cup size
- `professions` list (e.g. `["Actress", "Feature Dancer"]`)
- `photo_url` (350×350 profile thumbnail)
- `career_start` / `career_end` year strings
- `SocialLinks.pornhub` — allows FreeOnes → Pornhub cross-link via `ExternalIds.pornhub`

**ExternalIds to populate** on the `ProviderEntity` (not top-level `ExternalIds`):
- `entity.external_ids.freeones` — `performer.slug` (requires P9.0b)
- `entity.external_ids.pornhub` — `performer.social.pornhub` if non-empty (requires P9.0b)
- `entity.external_ids.extra["freeones_url"]` — `performer.url`
- `entity.external_ids.extra["freeones_photo_url"]` — `performer.photo_url`
- `entity.external_ids.extra["freeones_aliases"]` — `json.dumps(performer.aliases)`
- `entity.external_ids.extra["freeones_onlyfans"]` — `performer.social.onlyfans` if non-empty
- `entity.external_ids.extra["freeones_nationality"]` — `performer.nationality`

**Implementation shape**:
```python
class FreeonesProvider(MetadataProvider):
    name = "freeones"
    media = set()
    playback_type = set()

    def is_available(self) -> bool:
        try: import pyfreeones; return True
        except ImportError: return False

    def lookup(self, signals) -> None:
        return None

    def enrich(self, external_ids: ExternalIds) -> ExternalIds:
        return external_ids

def enrich_performer_entity(entity: ProviderEntity) -> ProviderEntity:
    """Look up performer by name, add FreeOnes data to entity.external_ids."""
    ...
```

**Test file**: `tests/test_providers_pyfreeones.py`
- Fixture: `tests/fixtures/freeones_bio.html` — minimal bio HTML with name, nationality, career_status, one social link
- `test_freeones_parse_bio_fixture`: call `parse_bio_page(html, "test-slug")`, assert `name` and `nationality` non-empty
- `test_freeones_social_pornhub_link`: fixture with known PH model URL in social section, assert `social["pornhub"]` extracted

---

### P9.7 — `pyhanime.py` — Hanime.tv hentai anime provider

**Upstream**: `../pyhanime/pyhanime/` (package `pyhanime`)
**Optional dep key**: `adult`
**MediaType**: `MediaType.SHORT_FILM` (single episodes); `MediaType.EPISODIC_SERIES` (franchises)

Hanime.tv hosts hentai anime with a rich data model — structured Brand (studio), Franchise (series), typed Tag objects, multi-server VideoStream with HLS + MP4 options.

**Key public API** (confirmed by reading source):
- `from pyhanime import get_video` — `get_video(slug: str)` → `Video` (no auth needed)
- `from pyhanime import get_franchise` — `get_franchise(franchise_slug: str)` → `List[VideoPreview]` (fetches ep-1 page internally)
- `from pyhanime import get_trending, get_new_releases, get_random` — no auth
- `from pyhanime.search import search, set_session_token` — `search(query, session_token)` requires auth
- `Video` fields: `id` (int), `name`, `slug`, `brand` (str), `brand_id` (str), `description_raw`, `is_censored`, `duration_in_ms`, `released_at`, `rating`, `tags: List[Tag]`, `streams: List[VideoStream]`, `franchise: Optional[Franchise]`, `franchise_episodes: List[VideoPreview]`, `best_stream` (property)
  - `Tag` fields: `id` (int), `text`, `count`, `description`
  - `VideoStream` fields: `url`, `height` (str), `width` (int), `kind` ("hls"/"mp4"), `is_guest_allowed`, `filesize_mbs`, `duration_in_ms`; `height_int` property
  - `Franchise` fields: `id` (int), `name`, `slug`

**Auth situation**: `search()` requires `HANIME_SESSION_TOKEN`. Direct `get_video(slug)` and browse work without auth. Without auth, `lookup()` returns `None`.

**ExternalIds fields to populate**:
- `external_ids.extra["hanime_slug"]` — `video.slug`
- `external_ids.extra["hanime_id"]` — `str(video.id)`
- `external_ids.extra["hanime_brand"]` — `video.brand`
- `external_ids.extra["hanime_brand_id"]` — `video.brand_id`
- `external_ids.extra["stream_url"]` — `video.best_stream.url` if present
- `external_ids.extra["hanime_franchise_slug"]` — `video.franchise.slug` if franchise present
- `external_ids.extra["tags"]` — `json.dumps([t.text for t in video.tags])` — do **not** emit tags as `ProviderEntity`

**Relations to emit**:
- `video.brand` (non-empty) → `ProviderEntity(role=EntityRole.STUDIO, name=video.brand)`

**Signals to populate**:
- `signals.title = video.name`
- `signals.runtime_seconds = video.duration_in_ms // 1000`
- `signals.year = video.released_at[:4]` if parseable

**Variants** (when franchise present):
- Emit one `ProviderEntity` per `VideoPreview` in `video.franchise_episodes` on `ProviderMatch.variants`
- Each: `ProviderEntity(role=EntityRole.OTHER, name=ep.name, external_ids=ExternalIds(extra={"hanime_slug": ep.slug}))`

**Lookup logic**:
- `HANIME_SESSION_TOKEN` set: `search(signals.title, token)` → pick best `VideoPreview` by title similarity → `get_video(preview.slug)`
- Not set: return `None` with `LOG.debug("pyhanime lookup requires HANIME_SESSION_TOKEN")`

**Enrich logic**: `extra["hanime_slug"]` → `get_video(slug)` → repopulate all

**Test file**: `tests/test_providers_pyhanime.py`
- Fixture: `tests/fixtures/hanime_video.json` — `Video.as_dict()` with franchise, brand, ≥2 tags, ≥1 stream
- `test_hanime_enrich_fixture`: mock `get_video`, assert `extra["hanime_slug"]` and `extra["stream_url"]` non-empty
- `test_hanime_studio_relation`: assert one `EntityRole.STUDIO` with the brand name
- `test_hanime_tags_in_extra_not_relations`: assert `extra["tags"]` is a JSON array, no `ProviderEntity` for tags
- `test_hanime_franchise_variants`: franchise set → assert `variants` non-empty
- `test_hanime_lookup_without_token`: unset `HANIME_SESSION_TOKEN`, assert `lookup()` returns `None`

---

### Phase 9 — pyproject.toml changes

```toml
radio      = ["tunein"]
audiobooks = ["audiobooker"]
youtube    = ["tutubo"]
adult      = ["pyfreeones", "pypornhub", "pyhanime", "pyiafd"]

all        = [
    "pyfanedit", "cinemagoer",
    "tunein",
    "audiobooker", "tutubo",
    "pyfreeones", "pypornhub", "pyhanime", "pyiafd",
]
```

---

### Phase 9 — docs/providers.md additions

- [ ] Add a row for each new provider: name, media types, auth (`none` / env var name), optional-dep key
- [ ] Mark adult providers with `⚠ adult content` in the description column
- [ ] Add "Content Warnings" subsection: `adult` extras are entirely optional and disabled by default; no adult providers load unless `pip install metadatarr[adult]`

---

### Phase 9 — Verification

```bash
# After P9.0 prerequisites:
python -c "from metadatarr.resolve.entities import EntityRole; assert EntityRole.ACTOR"
python -c "from mediavocab.models import ExternalIds; e = ExternalIds(); e.pornhub = 'test'; e.freeones = 'test'"
python -c "from pyfreeones import search_performers, get_performer"

# Per-provider smoke:
python -c "from metadatarr.resolve.providers import tunein"      # P9.1
python -c "from metadatarr.resolve.providers import audiobooker" # P9.2
python -c "from metadatarr.resolve.providers import tutubo"      # P9.3
python -c "from metadatarr.resolve.providers import pyiafd"      # P9.4
python -c "from metadatarr.resolve.providers import pypornhub"   # P9.5
python -c "from metadatarr.resolve.providers import pyfreeones"  # P9.6
python -c "from metadatarr.resolve.providers import pyhanime"    # P9.7

# Full suite:
python -m pytest tests/ -q --tb=short
ruff check metadatarr/
```
