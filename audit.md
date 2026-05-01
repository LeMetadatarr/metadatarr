# metadatarr — Code Audit

Audited: 2026-05-01
Version: 0.1.0a1 (pre-release)
Scope: all source under `metadatarr/`, test suite, pyproject.toml, docs

---

## Summary

metadatarr is a Pydantic-v2-powered Python library that provides:

1. HTTP clients for Servarr proxies (Sonarr/Radarr/Lidarr skyhook), OpenLibrary,
   Anna's Archive, AudioDB, TVmaze, Blu-ray.com (scraper), DVDCompare.net (scraper),
   and the Discogs REST API.
2. A cross-source entity resolution engine (`metadatarr.resolve`) that fans out to
   multiple provider backends, merges results by confidence, detects signal conflicts,
   and optionally enumerates release variants (fanedits, album pressings, etc.).
3. An entity sidecar system for stable deterministic IDs keyed by external authoritative
   IDs, with O(1) reverse-index lookup and atomic JSON persistence.
4. A TOML-based identity-mapping layer for asserting cross-platform equivalences that
   no API can prove (e.g. "this Bandcamp URL and this SoundCloud URL are the same
   artist").

The library is in alpha (0.1.0a1) and is not yet published publicly. The codebase is
architecturally mature for its scope: the resolver design is clean and extensible, the
signal-comparison model is well-thought-out, and the test suite is comprehensive for a
project at this stage.

---

## Strengths

**Architecture.** The provider plugin system is excellent. Providers are self-registering,
self-disabling (via `is_available()`), and isolated from each other. The `consolidate()`
confidence-weighted merge with explicit conflict diagnostics is the right design for
multi-source metadata: it does not silently pick a winner; it surfaces what disagreed and
why. Adding a new provider is genuinely two-step: write the class, call `register()`.

**Pydantic v2 model discipline.** Every public model uses `extra="ignore"` or
`extra="forbid"` deliberately. Field aliases cover both camelCase and PascalCase API
responses consistently. The `AliasChoices` / `AliasPath` use in `BaseMetadata` and
`LidarrArtist` handles the actual Lidarr artist-keyed payloads correctly. The
`model_validator(mode="before")` approach for flattening nested API fields (TVmaze image,
country, rating) is the right way to handle this in Pydantic v2.

**Signal comparison model.** `compare()` and `merged()` treat absent fields as
non-disagreement; the per-medium runtime tolerances (movies ±120 s, music ±3 s, etc.)
are sensible defaults; diacritic-folding plus feat-stripping in `_normalize_text` handles
real-world title noise. The conservative approach (any conflict = drop) is safer than a
weighted-average approach for a library that can't know its caller's tolerance.

**Test suite quality.** 346 tests, all passing, zero failures. The physical-client tests
are exemplary: real fixture files (captured HTML/JSON), direct parser calls, assertions
on specific field values. These tests will catch scraper regressions the moment the site
layout changes. Coverage is 88% overall on the core library (providers excluded by
policy), with the resolve layer at 82-98%.

**Caching infrastructure.** Both the in-process LRU (`_cache.py`) and the optional
disk-backed HTTP cache (`_http_cache.py`) are well-implemented. The LRU caches misses
(sentinel `_MISS`) so cold providers do not get re-queried on repeated calls; the disk
cache intercepts `requests.Session.send` globally and gracefully no-ops when the env var
is not set.

**Documentation.** The `docs/` directory is thorough for a pre-release library. Provider
pages explain what fields each client returns; the `resolve.md` and `recipes.md` pages
cover the full use-cases; inline docstrings are complete on public APIs.

---

## Issues Found

### CRITICAL (blocks correctness)

**C1: `BlurayComClient.get_edition()` always produces `url=None`.**

File: `metadatarr/client.py`, line 564.

```python
page_url = self._session.url if hasattr(self._session, "url") else None
```

`requests.Session` has no `.url` attribute. `hasattr(self._session, "url")` is always
`False`, so `page_url` is always `None`. The canonical URL after the `redirect.php`
redirect is on the `Response` object, not the `Session` object. The response is passed
directly to `BeautifulSoup` and discarded; its final URL is never captured.

`get_edition_by_url()` is unaffected (URL is passed explicitly). Only `get_edition(id)`
is broken.

Fix: store the response from `self._session.get(...)` before passing it to
BeautifulSoup, then read `resp.url`:

```python
resp = self._session.get(f"{_BLURAY_BASE}/movies/redirect.php",
                         params={"id": bluray_com_id},
                         timeout=self._timeout)
resp.raise_for_status()
page_url = resp.url
soup = BeautifulSoup(resp.text, "html.parser")
return self._parse_edition_page(soup, bluray_com_id, page_url)
```

---

### HIGH (functional gaps or reliability issues)

**H1: `ArrMetadataClient._get()` swallows all exceptions silently with no logging.**

File: `metadatarr/client.py`, lines 60-63.

```python
except Exception:
    return [] if "search" in url else {}
```

A rate-limit `429`, authentication failure `401`, DNS failure, or timeout all return the
same empty result. The caller has no way to distinguish "no results" from "network dead".
There is no `logging.warning()` or `logging.debug()` call. Compare this to
`MusicBrainzProvider._search()`, which logs `LOG.warning("MusicBrainz lookup failed: %s", e)`.

Fix: log the exception at `WARNING` level before returning the fallback. Ideally also
return `None` from `search_*` methods to let callers distinguish empty results from
errors, but that is a larger API change.

**H2: `_http_cache` test coverage is 26%. Core cache mechanics are untested.**

The `setup()`, `clear()`, `info()`, `_read_entry()`, `_write_entry()`, and
`_make_response()` functions have no tests. The monkey-patch that intercepts
`requests.Session.send` is permanent once installed and could interfere with other tests
if `METADATARR_HTTP_CACHE` is set in the test environment. There is no test that verifies
a cache hit actually returns the stored response rather than hitting the network.

Fix: add a `test_http_cache.py` that exercises `setup()` with a tmp dir, verifies round-
trip of a single cached response, verifies TTL expiry, and verifies `clear()`.

**H3: `AnnasArchiveClient` column indices are brittle hardcoded positions.**

File: `metadatarr/client.py`, lines 286-293.

```python
title = columns[1].get_text(strip=True)
author = columns[2].get_text(strip=True)
formats = columns[9].get_text(strip=True).upper()
language = columns[3].get_text(strip=True)
size = columns[8].get_text(strip=True)
```

Anna's Archive is a scraper target that changes its table structure periodically. A
column shift silently assigns wrong data to every field. There are no tests for the
scraper (no fixture HTML committed), so regressions will not be caught.

Fix: add a fixture HTML and tests. Inside the parser, use header-row column names to
build a `col_index` map rather than hardcoded positions.

**H4: `MusicBrainzProvider` uses outdated User-Agent URL.**

File: `metadatarr/resolve/providers/musicbrainz.py`, line 17.

```python
_UA = "metadatarr/0.1 (+https://github.com/TigreGotico/metadatarr)"
```

The GitHub URL is `TigreGotico/metadatarr` but the declared `pyproject.toml` homepage
is `JarbasAl/metadatarr`. MusicBrainz's web service policy requires a valid contact URL.
If MusicBrainz rate-limits or blocks the agent, all music lookups degrade silently.

Fix: update to `(+https://github.com/JarbasAl/metadatarr)` and keep it in sync with
`pyproject.toml`.

---

### MEDIUM (quality / design issues)

**M1: Duplicate dead code in `BlurayComClient._parse_edition_page()` genre fallback.**

File: `metadatarr/client.py`, lines 748-758.

The second `if not genres:` block starting at line 754 is a near-duplicate of the block
at line 748. The only difference is the regex: the first allows `/` in genre strings
(`[A-Za-z &/\-]+`); the second does not. The second block is reachable only if the
first `if not genres:` block ran AND populated nothing — but if the first block ran and
populated nothing, the second block has the same selectors and same conditions, and will
also populate nothing. The comment at line 753 is misplaced inside the first block's
indentation. This is dead code that adds noise.

Fix: remove the duplicate block.

**M2: `LidarrArtist` inherits a semantically wrong `title` field from `BaseMetadata`.**

`LidarrArtist` inherits `BaseMetadata.title` which resolves to the artist name. The
model also has its own `name` field that resolves to the same value. A `LidarrArtist`
instance has both `artist.title == "Daft Punk"` and `artist.name == "Daft Punk"`.
`title` has no meaning for an artist entity; it is a leaky abstraction from the base
class.

Fix: `LidarrArtist` should not extend `BaseMetadata`. It should be a standalone model.
The `title` field should be removed; `name` is the correct field.

**M3: `DiscogsClient._get()` imports `time` inside the method on every call.**

File: `metadatarr/client.py`, line 1229.

```python
import time as _time
```

This is inside `_get()`, which is called for every request. The stdlib `time` module
is cached after the first import so this is not a correctness bug, but it is bad Python
style. Move the import to module level.

**M4: `consolidate()` calls `apply_mappings()` for every `EntityKind` on every accepted
match, even when the match involves only one kind.**

File: `metadatarr/resolve/base.py`, lines 198-200.

```python
for kind in EntityKind:
    enriched = apply_mappings(kind, enriched)
```

There are 14 `EntityKind` values. For a movie resolution accepting 3 providers, this
triggers 42 mapping store lookups. Each lookup builds a `probe` dict over the full
`ExternalIds` field set (~30 fields). Most lookups will miss. This is not a correctness
issue but will be noticeable at scale.

Fix: call `apply_mappings` only for kinds present in the match's `relations`, plus
`EntityKind.OTHER` as a catch-all, or make `apply_mappings` accept an
`ExternalIds`-only call (without kind) that tries all kinds once.

**M5: `pyfanedit` is a hard dependency, not an optional extra.**

`pyproject.toml` lists `pyfanedit` under `[project.dependencies]`, not under
`[project.optional-dependencies]`. Users who only want book or music metadata are forced
to install `pyfanedit` (a scraper for fanedit.org). This is inconsistent with the pattern
used for all other optional integrations (`pymetal`, `py_bandcamp`, etc.).

Fix: move `pyfanedit` to `[project.optional-dependencies]` under a new `fanedits` extra,
and make `PyfaneditProvider.is_available()` check for the import rather than failing in
`__init__`.

**M6: `MappingStore._package_mappings_path()` uses `importlib.resources.as_file()`
context manager but returns the path after the context exits.**

File: `metadatarr/resolve/mappings.py`, lines 264-267.

```python
ref = resources.files("metadatarr.data").joinpath("mappings.toml")
with resources.as_file(ref) as p:
    return Path(p)
```

For installed wheels, `as_file()` may extract to a temporary path that is valid only
within the `with` block. Returning `Path(p)` after the context exits means the path may
refer to a deleted temp file when the package is installed from a zip/wheel.

Fix: read the file contents inside the `with` block and return the parsed TOML, rather
than returning the path. Alternatively, use `resources.files(...).joinpath(...).read_bytes()`
which does not require `as_file()`.

**M7: `Signals` has `extra="forbid"` but `include_variants` is a control flag mixed
into a data model.**

`include_variants: bool = False` is a resolver control flag that alters `resolve()`
behaviour. Mixing it into the `Signals` bag (a data model) means it participates in
`signal_hash()` (line 295: `include_variants` is absent from the hash fields but
`merged()` handles it separately) and `compare()` (ignored). This is a leaky design: two
`Signals` instances that are identical except for `include_variants` hash identically
but behave differently in `resolve()`.

This is not a bug today (caching is per-`(provider, signal_hash)` and the providers
themselves never see `include_variants`), but it is a design smell.

**M8: `ExternalIds.extra` type is `Dict[str, str]` but several internal callers store
typed values coerced to strings.**

In multiple providers, integer IDs are stored in `extra` as `str(id)`. This means
callers who read back from `extra` must know which keys contain integers. The field name
convention (e.g. `audiodb_artist_id`) has no type annotation. A `Dict[str, Any]` or a
typed `extra` model would be cleaner, but changing `extra` to `Dict[str, Any]` would
require revisiting all type annotations and may cause Pydantic validation differences.
Documenting the string-representation convention explicitly would be sufficient.

---

### LOW (minor issues / nits)

**L1: `OpenLibrarySearchHit.work_id` is a `@property` that returns `Optional[str]`,
not a model field.** Callers who do `hit.model_dump()` will not get `work_id` in the
output. This is surprising. Consider making it a `@computed_field`.

**L2: `TVmazeProvider.lookup()` builds a duck-type fallback for missing `externals`:**
```python
ext = top.externals or type("_", (), {"thetvdb": None, "imdb": None, "tvrage": None})()
```
This anonymous class is unnecessary — `TVmazeExternals` already has all fields optional.
`top.externals` can only be `None` if the API returned no `externals` key, and accessing
`getattr(ext, "imdb", None)` later is the correct guard. The anonymous class adds
confusion. Use `top.externals` directly with None-guards.

**L3: `ArrMetadataClient` `User-Agent` default is `"ArrMetadataClient/1.0"` which does
not identify the library.** Other clients use `"metadatarr/1.0"`. Use the library name
consistently.

**L4: `test_clients_deep.py` has 33 tests but `test_clients.py` has 9, and they both
test similar surface area.** Consider consolidating into a single file.

**L5: `BlurayComClient._parse_edition_page()` is 307 lines.** This function does title
extraction, year extraction, spec-block parsing, audio-track parsing, subtitle parsing,
disc-format parsing, packaging parsing, community-stats extraction, label extraction,
IMDb extraction, rating extraction, and extras extraction. It is doing too many things.
No individual piece is wrong, but testability and maintainability would improve with
decomposition into private `_parse_*` helpers, each testable independently.

**L6: `metadatarr/resolve/providers/musicbrainz.py` line 63 uses `list[ProviderEntity]`
(lowercase) instead of `List[ProviderEntity]`.** This requires Python 3.9+ which matches
the declared `requires-python = ">=3.9"`, but the rest of the codebase uses `from typing
import List` and `List[...]` for consistency. Minor style inconsistency.

---

## Test Coverage Assessment

| Module | Coverage | Notes |
|---|---|---|
| `__init__.py` | 100% | trivial |
| `client.py` | 89% | missing: AnnasArchiveClient scraper, BlurayComClient search(), get_edition() redirect path |
| `models.py` | 93% | missing: some validator branches |
| `resolve/base.py` | 82% | missing: `list_variants` collection logic (lines 295-320), `enrich()` pool path |
| `resolve/signals.py` | 95% | good |
| `resolve/external_ids.py` | 97% | good |
| `resolve/entities.py` | 98% | excellent |
| `resolve/mappings.py` | 91% | missing: tomllib ImportError path |
| `resolve/sidecar.py` | 89% | missing: error cleanup in `save()` |
| `resolve/_cache.py` | 94% | good |
| `resolve/_http_cache.py` | 26% | **critical gap** — core mechanics untested |
| Providers (excluded) | n/a | integration-tested via examples only |

Total: 88% on measured modules, 346 tests passing.

The 26% on `_http_cache` is the only genuinely worrying gap. The module patches
`requests.Session.send` globally and the patch is irreversible for the process lifetime;
its behaviour needs unit tests before the library ships publicly.

---

## Recommended Fixes (Priority Order)

1. **Fix C1** (`get_edition()` URL tracking bug) — one-line fix, high user impact.

2. **Fix H4** (MusicBrainz User-Agent URL mismatch) — one-line fix, prevents API blocks.

3. **Fix H1** (silent exception swallowing in `ArrMetadataClient._get()`) — add
   `logging.warning()` inside the `except` block. No API change required.

4. **Fix M6** (`_package_mappings_path()` context-manager path lifetime bug) — refactor
   to read bytes inside the `with` block.

5. **Fix M5** (move `pyfanedit` to optional dep) — packaging change, no behaviour change.

6. **Fix M1** (dead duplicate genre block in `_parse_edition_page()`) — delete 5 lines.

7. **Add H2** (http_cache tests) — new test file, no code changes required.

8. **Add H3** (AnnasArchive fixture + header-based column parsing) — medium effort,
   prevents silent misparsing on site changes.

9. **Address L6** (lowercase `list` type hint in musicbrainz provider) — cosmetic but
   maintains codebase consistency.

10. **Address M2** (`LidarrArtist` base class) — breaking API change, low urgency while
    pre-release.

---

## Architecture Notes

The resolve engine's design is sound and worth preserving as-is. The two-stage
`search()` / `consolidate()` split (introduced in the unreleased changelog) is better
than the old single-call design: it lets callers inspect candidates before committing to
a merge and enables the `search(signals)[:5]` UI pattern.

The `ExternalIds.extra: Dict[str, str]` field is doing significant work for provider
extensibility without adding new model fields. This is pragmatic but means type safety
for extended IDs relies on naming conventions rather than schemas. As the provider
ecosystem grows, consider a typed `ProviderExtras` union or at minimum a
`KNOWN_EXTRA_KEYS` constant listing documented keys to prevent silent typos.

The TOML-based mapping system is one of the more interesting pieces of the library.
Asserting cross-platform identity clusters at the process level (with an in-memory store
plus a user config file) is exactly the right approach for the long tail of artists and
albums that no single API can definitively link. The `score` field on `MappingEntry`
positions this for future use as a probabilistic seeding layer — worth preserving.
