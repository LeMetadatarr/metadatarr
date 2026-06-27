# Adding a provider

A *provider* is a small adapter that, given a [`Signals`](resolve.md) bag,
returns a `ProviderMatch` with whatever cross-references it could resolve from
one upstream catalogue. Providers self-register on import; the resolver fans out
to every registered, available provider that matches the request's three routing
axes.

This page is the end-to-end checklist for writing one. For the runnable version
see [`examples/learn/08_writing_a_provider.py`](../examples/learn/08_writing_a_provider.py)
and [`examples/variant_custom_provider.py`](../examples/variant_custom_provider.py).

## The shape

Subclass `MetadataProvider`, fill in the class attributes, implement
`is_available()` and `lookup()`, then `register()` an instance.

```python
from typing import ClassVar, Optional, Set

from mediavocab import MediaType, PlaybackType, Signals, ExternalIds
from mediavocab.models.signals import match_quality
from mediavocab.taxonomy import GENRE_ANIME
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register

import logging
LOG = logging.getLogger("metadatarr.resolve.providers.mycat")


class MyCatalogueProvider(MetadataProvider):
    name: ClassVar[str] = "mycat"                      # unique registry key
    media: ClassVar[Set[MediaType]] = {MediaType.MOVIE}
    playback_type: ClassVar[Set[PlaybackType]] = {PlaybackType.VIDEO}
    genre_filter: ClassVar[Set[str]] = set()          # e.g. {GENRE_ANIME}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        try:
            hit = _search_upstream(signals.title)        # your HTTP call
        except requests.RequestException as exc:
            LOG.warning("mycat lookup failed query=%r: %s", signals.title, exc)
            return None
        except Exception:
            LOG.exception("mycat lookup unexpected error query=%r", signals.title)
            return None
        if hit is None:
            return None
        cand = Signals(title=hit.title, year=hit.year, medium=MediaType.MOVIE)
        return ProviderMatch(
            provider=self.name,
            confidence=0.8 * match_quality(signals, cand),
            signals=cand,
            external_ids=ExternalIds(imdb=hit.imdb, tmdb_movie=hit.tmdb_id),
        )


register(MyCatalogueProvider())
```

## Checklist

### 1. Declare identity and the three routing axes

| Attribute | Required | Purpose |
|---|---|---|
| `name` | **yes** | Unique key in the registry. `register()` raises if empty. |
| `media` | no | Which `MediaType` values you serve. Empty set = no restriction. |
| `playback_type` | no | Which `PlaybackType` values (`AUDIO`/`VIDEO`/`INTERACTIVE`/`TEXT`/`UNKNOWN`). Lets a `MediaType.GENERIC` query route to you by modality. |
| `genre_filter` | no | Genre tags (from `mediavocab.taxonomy`). Anime/manga gating uses this, **not** a fake `MediaType.ANIME`. |

A provider matches a request when **all three** gates pass (each gate is a
no-op if its set is empty). See `MetadataProvider.matches()` in
[`resolve/base.py`](../metadatarr/resolve/base.py).

### 2. `is_available()` → `bool`

Return `False` when the provider can't run: a missing optional dependency, an
unset API key/env var, or an unreachable required service. The resolver skips
unavailable providers silently — never raise here.

```python
def is_available(self) -> bool:
    try:
        import some_optional_dep  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("MYCAT_TOKEN"))
```

### 3. `lookup(signals)` → `ProviderMatch | None`, **never raises**

This is the error contract — the whole resolver is silent-failure by design:

- Return `None` when you have nothing (no title, wrong medium, no match).
- **Swallow, log, return `None`** on any error. Catch `requests.RequestException`
  with a `LOG.warning(... query=...)`; catch unexpected `Exception` with a final
  `LOG.exception(...)`; return `None` either way.
- Never let an exception escape — one flaky provider must not break a fan-out
  that touches a dozen others.

### 4. Confidence scale: 0.5 – 0.95

`ProviderMatch.confidence` ranks candidates and anchors consolidation
(strongest first). Use the band consistently:

| Range | When |
|---|---|
| **0.9 – 0.95** | Exact authoritative-ID hit, or a local/curated catalogue. |
| **0.7 – 0.85** | Strong-signal search (title + year/artist agree). |
| **0.5 – 0.6** | Fuzzy search, or an inherently noisy/unreliable source. |

Multiply your base confidence by `match_quality(signals, candidate_signals)` so
weak title/year/artist agreement scales the score down automatically.

### 5. Emit only canonical mediavocab values

Anything you put on `Signals` or `ExternalIds` must be a canonical mediavocab
value, never an ad-hoc string:

- `content_genres` ⊆ `mediavocab.taxonomy.KNOWN_GENRES` — use the `GENRE_*`
  constants (`GENRE_ANIME`, not `"anime"`).
- `picture_format` → `PictureFormat`; `programme_format` → `ProgrammeFormat`
  (news/documentary/talk-show/sports are **ProgrammeFormat**, not genres);
  `accessibility` → `AccessibilityKind`; `structure` → `Structure`.
- `source_format` is for distribution/container only (vinyl, blu-ray, vhs, …).

A guard test (`tests/test_provider_genre_emission.py`) asserts no provider emits
a non-`KNOWN_GENRES` genre string, so a stray literal fails CI.

### 6. Optional overrides

- `lookup_candidates(signals) -> List[ProviderMatch]` — override when the
  upstream API can cheaply rank multiple candidates and you want `consolidate()`
  to pick across providers (namesake bands, ambiguous people). Default wraps
  `lookup()`.
- `list_variants(external_ids, signals) -> List[ProviderEntity]` — return
  release/cut/edition entities when `signals.include_variants=True`. Default
  `[]`.
- `enrich(external_ids) -> ExternalIds | None` — given IDs, derive *more* IDs
  without a free-text search (ID-keyed lookups). Return only the enrichment;
  the framework merges it first-writer-wins. Default `None`.

All overrides follow the same never-raise contract as `lookup()`.

### 7. `register()`

Call `register(MyCatalogueProvider())` at module bottom. Built-in providers are
imported (and thus registered) by `metadatarr/resolve/providers/__init__.py`.
For an out-of-tree provider, just import your module before calling `resolve()`.

## Testing your provider

See [testing.md](testing.md) for the offline-fixture / mocked-HTTP pattern and
the parametrized per-provider smoke test every provider must pass.
