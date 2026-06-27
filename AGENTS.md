# AGENTS.md — metadatarr

Pydantic-powered media-metadata clients plus a keyless cross-source entity resolver that fuses public catalogues (Servarr proxies, MusicBrainz, Wikidata, OpenLibrary, Discogs, AniList/Jikan, AudioDB, TVmaze, and bundled scrapers) into one de-duplicated record with canonical `ExternalIds`.

## Setup
```bash
pip install -e ".[test]"
```
Core install pulls `mediavocab` plus the first-party scrapers (`pyfanedit`, `pymetal`, `tutubo`, `py_bandcamp`, `nuvem_de_som`) as hard dependencies — no optional extras needed for the resolver to work. The only extra is `[test]`.

## Test
```bash
pytest
```
Tests live in `tests/` (configured via `[tool.pytest.ini_options]`, `addopts = -q`). Fully offline — all HTTP is stubbed with fixture/cassette files (`tests/test_*_cassette.py`).

## Lint/Typecheck
Ruff is enabled via CI (`.github/workflows/lint.yml` -> gh-automations `lint.yml@dev` with `ruff: true`). Run `ruff check .` locally. No mypy config. Coverage config in `pyproject.toml` excludes `resolve/providers/*` (those are integration-tested via `examples/`).

## Layout
- `metadatarr/client.py` — direct typed clients (`ArrMetadataClient`, `OpenLibraryClient`, `BookInfoClient`, `AnnasArchiveClient`, `AudioDBClient`, `TVmazeClient`).
- `metadatarr/models.py` — Pydantic V2 response models for the direct clients (Sonarr/Radarr/Lidarr, OpenLibrary, BookInfo, DVDCompare, etc.).
- `metadatarr/resolve/base.py` — resolver core: `MetadataProvider` ABC, `ProviderMatch`, `ResolveResult`, three-axis routing (media/modality/genre), the process-global provider registry (`register`), and `consolidate`/`resolve`.
- `metadatarr/resolve/providers/` — ~35 provider shims, one per source; self-register on import. Each maps a source's response into `ProviderMatch` with `ExternalIds`.
- `metadatarr/resolve/entities.py` — `ProviderEntity`, `EntityRole`, entity-id allocation for relations/variants.
- `metadatarr/resolve/mappings.py` + `metadatarr/data/mappings.toml` — curated cross-platform identity links; user file at `~/.config/metadatarr/mappings.toml` extends it.
- `metadatarr/resolve/_cache.py`, `_http_cache.py` — process-level result + HTTP caching (hits and misses both cached).
- `metadatarr/resolve/title_parser.py`, `sidecar.py` — filename/title parsing and sidecar helpers.
- `examples/` — one focused script per use case; `docs/` — getting-started, models, resolve, providers, recipes, physical-disc, troubleshooting, per-client deep dives.

## Conventions (Org hard rules)
- Branches: `dev` (work) / `master` (stable). NEVER `main`.
- Never edit `metadatarr/version.py`; gh-automations bumps semver from conventional-commit prefixes (`feat:`/`fix:`/`feat!:`).
- New repos private by default.
- Commit identity: `JarbasAi <jarbasai@mailfence.com>`.
- Reference `OpenVoiceOS/gh-automations` reusable workflows at `@dev`.
- No Neon / `neon-*` references.
- No meta-commentary in code/docs/commits (no history, dates, or "before times"); describe current state only.
- CI is provided by `OpenVoiceOS/gh-automations`.

## Gotchas
- The resolver depends on `mediavocab` types (`Signals`, `MediaType`, `ExternalIds`, `PlaybackType`, `SignalConflict`); imports mix `from mediavocab import ...` and `from mediavocab.models...` — keep both in sync with the mediavocab spec.
- Routing is three-axis: `media`, `modality`, `genre_filter`. `MediaType.GENERIC` queries are routed by the `modality` field on `Signals`. A provider must refuse mediums outside its `media` set (return `None`).
- `youtube` and `youtube_music` are deliberately separate: `youtube` emits only channel IDs and refuses `MediaType.MUSIC`; `youtube_music` emits stable `browseId` entity records.
- Provider shims guard optional imports in `try/except ImportError` and set unavailable; coverage intentionally omits `resolve/providers/*`.
- `include_variants=True` triggers a second pass calling `list_variants()` (e.g. pyfanedit cuts, MusicBrainz release-group expansion).
- Canonical numeric IDs only as typed `ExternalIds` fields; URL slugs go into the `extra` dict as `*_url` keys.
