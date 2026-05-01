# Entity resolution

`metadatarr.resolve` is a provider-based metadata enrichment layer.  Given a
handful of signals about a work (title, artist, year, runtime, medium) it
fans out to every configured provider, merges the results, and hands back a
single coherent set of external IDs plus typed entity relations (artists,
albums, channels, …).

---

## Concepts

### Signals

A `Signals` object is the input to every lookup.  It carries what you already
know about the work:

```python
from metadatarr.resolve.signals import Signals, Medium

signals = Signals(
    title="Sankarihauta",
    artist="Moonsorrow",
    year=2003,
    medium=Medium.MUSIC,
)
```

All fields are optional — pass as much or as little as you have.  The more
context you provide, the better providers can filter their results and the
more aggressively `consolidate()` can reject mismatches.

| Field | Type | Purpose |
|---|---|---|
| `title` | `str` | Work title |
| `artist` | `str` | Primary artist / director / author |
| `year` | `int` | Release year |
| `runtime` | `float` | Duration in seconds |
| `medium` | `Medium` | Content category (see below) |
| `language` | `str` | ISO 639-1 code |
| `country` | `str` | ISO 3166-1 alpha-2 code |
| `season` | `int` | TV season number (TV episodes only) |
| `episode` | `int` | TV episode number (TV episodes only) |
| `variant_kind` | `VariantKind` | Cut / edition discriminator (see below) |
| `edition` | `str` | Free-text edition name (e.g. `"25th Anniversary"`) |
| `region` | `str` | ISO 3166-1 alpha-2; release territory (distinct from work-origin `country`) |
| `source_format` | `str` | Physical / digital format (e.g. `"4K"`, `"Blu-ray"`, `"Vinyl"`) |
| `include_variants` | `bool` | When `True`, `resolve()` fans out to variant-aware providers and populates `result.relations[Role.RELEASE]` |

`Signals` — `metadatarr/resolve/signals.py:74`

**`Medium` values** — `MUSIC`, `MUSIC_VIDEO`, `MOVIE`, `TV`, `PODCAST`, `BOOK`, `OTHER`.

`MUSIC_VIDEO` covers concert films, official music videos, and live performances on physical video media (LaserDisc, VHS, DVD).  It is the medium for Discogs music-video searches.  `Medium` — `metadatarr/resolve/signals.py:46`

#### VariantKind

`VariantKind` — `metadatarr/resolve/signals.py:54`

A string enum that classifies cuts and editions for conflict detection.
`compare()` treats two bags as conflicting on `variant_kind` only when both
sides set it and the values differ; an absent value is never a conflict.

| Value | Applies to |
|---|---|
| `THEATRICAL` | Film — original theatrical cut |
| `DIRECTORS` | Film — director's cut |
| `EXTENDED` | Film or album — extended version |
| `FANEDIT` | Film — fan-edited cut |
| `COLORIZED` | Film — colourised version of B&W original |
| `UPSCALED` | Film — AI/manual upscale |
| `STANDARD` | Album — standard edition |
| `DELUXE` | Album — deluxe edition |
| `BONUS_TRACKS` | Album — bonus-tracks edition |
| `REISSUE` | Album — reissue |
| `COMPILATION` | Album — compilation |
| `REGIONAL` | Film or album — territory-specific release |
| `REMASTERED` | Film or album — remastered |
| `OTHER` | Anything else |
Setting `medium` controls which providers are even asked: a `Medium.MUSIC`
lookup never touches the TVmaze TV provider; a `Medium.MOVIE` lookup
never touches Bandcamp.

#### Title comparison

Titles are matched fuzzily after a normalisation pass that:

1. Folds Unicode diacritics via NFKD (so `Café` and `cafe` compare equal,
   `Pokémon` and `Pokemon` are the same work, etc.); base characters of
   any script are kept intact.
2. Strips parenthetical qualifiers, "feat. …" / "ft. …" segments, and
   collapses punctuation/whitespace to single spaces.

Two titles agree when their `difflib` ratio after normalisation is at
least `TITLE_FUZZY_MIN` (default `0.92`).

#### Runtime tolerance

`compare()` uses `RUNTIME_TOLERANCE_BY_MEDIUM_S` (movies ±120 s, TV ±30 s,
music ±3 s, music\_video ±30 s, books `0`, podcast ±30 s, other ±5 s) when
both sides declare a `medium`. Falls back to `RUNTIME_TOLERANCE_S` (5 s)
when neither side does.  `RUNTIME_TOLERANCE_BY_MEDIUM_S` — `metadatarr/resolve/signals.py:35`

#### `match_quality()`

`metadatarr.resolve.match_quality(local, candidate)` returns a `[0.0, 1.0]`
score combining title fuzzy ratio, year agreement, and medium agreement.
Built-in providers multiply their base confidence by this score so a
strong upstream that returned the *wrong* record doesn't outvote a weaker
upstream that returned the *right* one.

### ExternalIds

The output of a successful lookup is an `ExternalIds` instance.  It has
first-class typed fields for every well-known platform ID, plus an `extra`
dict for everything else:

```python
from metadatarr.resolve.external_ids import ExternalIds

ids = ExternalIds(
    musicbrainz_artist="some-uuid",
    metal_archives_band=3540328893,
    extra={
        "bandcamp_band_id": "12345678",
        "youtube_music_artist_browse_id": "UCxxxxx",
    },
)
```

First-class fields (all optional, typed):

| Field | Type | Platform |
|---|---|---|
| `musicbrainz_recording` | `str` | MusicBrainz |
| `musicbrainz_release` | `str` | MusicBrainz |
| `musicbrainz_release_group` | `str` | MusicBrainz |
| `musicbrainz_work` | `str` | MusicBrainz |
| `musicbrainz_artist` | `str` | MusicBrainz |
| `imdb` | `str` | IMDb (tt-id) |
| `tmdb_movie` | `int` | TMDB |
| `tmdb_tv` | `int` | TMDB |
| `tvdb` | `int` | TVDB |
| `isbn_10` / `isbn_13` | `str` | Books |
| `olid` | `str` | OpenLibrary |
| `goodreads` | `str` | Goodreads |
| `wikidata` | `str` | Wikidata (Q-id) |
| `tmdb_person` | `int` | TMDB person |
| `imdb_person` | `str` | IMDb person (nm-id) |
| `metal_archives_band` | `int` | Encyclopaedia Metallum |
| `metal_archives_release` | `int` | Encyclopaedia Metallum |
| `metal_archives_song` | `str` | Encyclopaedia Metallum (alphanumeric lyrics-id form returned by song search) |
| `metal_archives_label` | `int` | Encyclopaedia Metallum |
| `metal_archives_artist` | `int` | Encyclopaedia Metallum |
| `fanedit_id` | `int` | IFDB (fanedit.org) WordPress post ID |
| `derived_from_imdb` | `str` | Parent IMDb tt-id; set on records that *are* variants of another work |
| `discogs_release` | `int` | Discogs numeric release ID |
| `bluray_com_id` | `int` | blu-ray.com movie page ID |
| `dvdcompare_id` | `str` | dvdcompare.net edition slug |

`ExternalIds` — `metadatarr/resolve/external_ids.py:56`

Everything a provider emits that doesn't have a first-class slot lands in
`extra` as `str → str`.  Common extra keys:

| Key | Platform |
|---|---|
| `bandcamp_band_id` | Bandcamp numeric artist id |
| `bandcamp_track_id` | Bandcamp numeric track id |
| `bandcamp_album_id` | Bandcamp numeric album id |
| `bandcamp_*_url` | Bandcamp page URLs (metadata, not canonical ids) |
| `soundcloud_user_id` | SoundCloud numeric user id |
| `soundcloud_track_id` | SoundCloud numeric track id |
| `soundcloud_*_url` | SoundCloud page URLs |
| `youtube_video_id` | YouTube upload id (11 chars) |
| `youtube_channel_id` | YouTube channel id (`UCxxx` or `@handle`) |
| `youtube_music_video_id` | YouTube Music track id |
| `youtube_music_artist_browse_id` | YouTube Music artist entity id |
| `youtube_music_album_browse_id` | YouTube Music album entity id |
| `youtube_music_playlist_id` | YouTube Music album playlist id |
| `youtube_content_type` | Classifier hint from tutubo |

#### ISBN normalisation

`ExternalIds` runs an `@model_validator(mode="after")` that:

1. Strips formatting (hyphens / spaces / non-digits, preserving a trailing
   `X` check digit) from `isbn_10` and `isbn_13`;
2. Back-fills the sibling form when only one is given (978-prefixed
   ISBN-13s have an ISBN-10 representation; non-978 13s do not).

So `ExternalIds(isbn_10="0-261-10328-8")` ends up with both
`isbn_10="0261103288"` and `isbn_13="9780261103283"`. Two providers that
disagree on representation merge cleanly.

The conversion helpers are public:
`metadatarr.resolve.external_ids.isbn10_to_13`,
`isbn13_to_10`, and `normalize_isbn`.

#### Merge semantics

`ExternalIds.merge(other)` is **first-writer-wins** — fields already set
on `self` are preserved, `other` only fills in empty slots. The same
applies inside `extra`. Combine with `consolidate()`'s confidence
ordering and the strongest provider's IDs anchor the result.

### Entities

Providers don't just return IDs for the work itself — they also return
**relations**: typed pointers to related entities (the artist, the album the
track is on, the director, the publisher, …).

```python
from metadatarr.resolve.entities import EntityKind, ProviderEntity

# A provider match may include:
match.relations = {
    EntityKind.ARTIST: [ProviderEntity(
        kind=EntityKind.ARTIST,
        name="Moonsorrow",
        external_ids=ExternalIds(extra={"bandcamp_band_id": "12345678"}),
    )],
    EntityKind.ALBUM: [...],
}
```

Entity kinds: `ARTIST`, `ALBUM`, `RELEASE`, `TRACK`, `LABEL`, `CHANNEL`,
`ACTOR`, `DIRECTOR`, `PRODUCER`, `COMPOSER`, `WRITER`, `NARRATOR`, `HOST`,
`AUTHOR`, `OTHER`.

`EntityKind` — `metadatarr/resolve/entities.py:30`

`RELEASE` is used for specific releases / cuts of a work (individual MusicBrainz
releases within a release-group, or fanedit.org entries). It is the kind stored
in `result.relations[Role.RELEASE]` when `include_variants=True`.

Entities get their own stable IDs via `allocate_entity_id()`, which derives a
deterministic SHA1 from the strongest known external ID (MusicBrainz > Metal
Archives > Wikidata > platform numeric id > …).  Two providers referencing
the same MusicBrainz artist will always produce the same entity ID.

---

## Providers

Each provider is an optional-dependency plugin that self-registers on import.
If the required library is not installed, `is_available()` returns `False`
and the provider is silently skipped.

### Built-in (always active)

| Name | Source | Notes |
|---|---|---|
| `musicbrainz` | MusicBrainz API | Music — artist, release, recording IDs |
| `wikidata` | Wikidata API | Cross-domain — Wikidata Q-id + cross-references |
| `tvmaze` | TVmaze public API | TV — no auth required |
| `audiodb` | TheAudioDB | Music — free public key, no auth |
| `metadatarr` | Servarr metadata-server proxies (skyhook, radarrapi, api.lidarr.audio) + OpenLibrary | Proxy — no env vars needed |

### Optional — music

| Name | Dep | Notes |
|---|---|---|
| `bandcamp` | `py_bandcamp` | Numeric `band_id`/`track_id`/`album_id` from data-tralbum |
| `soundcloud` | `nuvem_de_som` | Numeric `user_id`/`track_id` |
| `youtube_music` | `tutubo` | Artist + album browseIds; refuses non-music lookups |
| `metal_archives` | `pymetal` | Encyclopaedia Metallum numeric IDs |

### Optional — video / other

| Name | Dep | Notes |
|---|---|---|
| `youtube` | `tutubo` | Regular YouTube — channel + upload IDs only; refuses `MUSIC` |
| `pyfanedit` | none — hard dep | Variant-only (movie); `lookup()` returns `None`; `list_variants()` queries fanedit.org (IFDB) via `search_by_original_title()` — `metadatarr/resolve/providers/pyfanedit.py:61` |

### Installing optional providers

```bash
pip install "metadatarr[bandcamp]"          # py_bandcamp
pip install "metadatarr[soundcloud]"        # nuvem_de_som
pip install "metadatarr[youtube]"           # tutubo (covers both YT providers)
pip install "metadatarr[metal_archives]"    # pymetal
pip install "metadatarr[all]"              # everything above
```

`pyfanedit` (fanedit.org / IFDB) is a **core dependency** — no extra install required.

### Multiple candidates per provider

Each provider exposes two lookup methods:

- `lookup(signals) -> Optional[ProviderMatch]` — the single best match
  (used by direct callers).
- `lookup_candidates(signals) -> List[ProviderMatch]` — up to N ranked
  candidates, highest confidence first (used by `resolve()` so
  `consolidate()` can pick across providers).

Default `lookup_candidates` wraps `lookup`. Built-in overrides:

| Provider | Top-N | Cost |
|---|---|---|
| `musicbrainz` | 5 | a single recording search returns all candidates |
| `wikidata` | 3 | one search + one entity fetch per candidate |
| `metal_archives` | 5 | a single song search returns all candidates |

Providers without an override still emit a single candidate (their
`lookup()` result) and participate in confidence ordering normally.

### Querying the registry

```python
from metadatarr.resolve.base import all_providers, active_providers
from metadatarr.resolve.signals import Medium

all_providers()                         # {name: provider} — every registered provider
active_providers()                      # those whose is_available() is True
active_providers(medium=Medium.MUSIC)   # further filtered to music-capable providers
```

---

## Running a lookup

### Simple — `resolve()`

```python
import metadatarr.resolve.providers          # triggers provider self-registration
from metadatarr.resolve.base import resolve
from metadatarr.resolve.signals import Signals, Medium

result = resolve(Signals(title="Inception", medium=Medium.MOVIE))
print(result.external_ids.tmdb_movie)   # → 27205
print([m.provider for m in result.accepted])
print([m.provider for m in result.dropped])
```

`resolve()` fans out to every active provider whose `media` set includes the
requested medium and calls `consolidate()` on the combined candidates.

Two things to know about how it runs:

- **Concurrent.** Provider lookups run in parallel via a
  `ThreadPoolExecutor` (bounded by `max_workers`, default `8`). Pass
  `resolve(signals, max_workers=N)` to tune.
- **Cached.** Each lookup is keyed on `(provider.name, signal_hash(signals))`
  and goes through a process-wide LRU. Both **hits** and **misses** are
  cached, so failed lookups don't re-hit the network. Inspect or clear via
  `metadatarr.resolve._cache.cache()`.

  ```python
  from metadatarr.resolve._cache import cache

  cache().hits, cache().misses    # diagnostics
  cache().clear()                 # force re-fetch
  ```

### Manual — `consolidate()`

For cases where you control which providers run or want to supply pre-fetched
matches:

```python
from metadatarr.resolve.base import active_providers, consolidate, ProviderMatch
from metadatarr.resolve.signals import Signals, Medium

signals = Signals(title="Inception", medium=Medium.MOVIE)
matches = []
for provider in active_providers(medium=signals.medium):
    match = provider.lookup(signals)
    if match:
        matches.append(match)

result = consolidate(matches, signals)
print(result.external_ids.tmdb_movie)
```

### `ResolveResult` fields

| Field | Type | Description |
|---|---|---|
| `signals` | `Signals \| None` | Merged signals from accepted matches; `None` on irreconcilable conflict |
| `external_ids` | `ExternalIds` | Merged IDs from accepted matches, enriched by mappings |
| `accepted` | `List[ProviderMatch]` | Matches that agreed with local signals and each other (sorted by confidence desc) |
| `dropped` | `List[ProviderMatch]` | Matches dropped for conflicting with local signals or the running consolidation |
| `conflicts` | `List[ResolutionConflict]` | Per-drop diagnostic — which provider clashed, with what, on which fields |
| `relations` | `Dict[Role, List[ProviderEntity]]` | Variant entities; populated only when `signals.include_variants=True`; key is `Role.RELEASE` |

`ResolveResult` — `metadatarr/resolve/base.py:56`

#### Variant fan-out

When `signals.include_variants=True`, `resolve()` runs a second pass after
consolidation. It calls `list_variants(result.external_ids, signals)` on
every active provider whose `media` set includes the requested medium.
Results are de-duplicated by `fanedit_id` > `musicbrainz_release` > `name`
(first seen wins) and stored in `result.relations[Role.RELEASE]`.

```python
from metadatarr.resolve.base import resolve
from metadatarr.resolve.entities import Role
from metadatarr.resolve.signals import Signals, Medium

result = resolve(Signals(
    title="Inception",
    medium=Medium.MOVIE,
    include_variants=True,
))
for entity in result.relations.get(Role.RELEASE, []):
    print(entity.name, entity.external_ids.fanedit_id)
```

`resolve()` variant fan-out — `metadatarr/resolve/base.py:276`

`consolidate()` consumes matches **highest-confidence first**, so the
strongest provider anchors the consensus regardless of input order.

### Conflict detection

`compare(a, b)` returns a list of `SignalConflict` describing every field
where `a` and `b` disagree beyond tolerance:

- **Title** — fuzzy ratio must be ≥ `TITLE_FUZZY_MIN` (`0.92`).
- **Artist** — fuzzy ratio must be ≥ `ARTIST_FUZZY_MIN` (`0.90`).
- **Year** — must agree within `YEAR_TOLERANCE` (±1 year).
- **Runtime** — per-medium tolerance (movies ±120 s, TV ±30 s, music ±3 s,
  books `0`, podcast ±30 s, other ±5 s; see
  `RUNTIME_TOLERANCE_BY_MEDIUM_S`).
- **Medium** / **country** / **language** — exact match when both set.
- **Season** / **episode** — exact match when both set.
- **Variant kind** — exact match when both set; absent on either side is not a conflict.
- **Region** — case-insensitive exact match when both set.
- **Source format** — case-insensitive exact match when both set.

A match is dropped if it conflicts with `local`. The consolidation marks
the result `signals=None` if two already-accepted matches conflict with
each other.

`ResolutionConflict` lets the caller introspect *why* something was
dropped without re-running `compare()`:

```python
from metadatarr.resolve import resolve, Medium, Signals

result = resolve(Signals(title="Inception", year=2010, medium=Medium.MOVIE))
for diag in result.conflicts:
    fields = ", ".join(f"{c.signal}({c.ours}≠{c.theirs})" for c in diag.fields)
    print(f"{diag.provider:<20} clashed with {diag.against}: {fields}")
```

`diag.against` is `"local"` when the match conflicted with the input
signals, otherwise the name of the previously-accepted provider that
anchored the consensus.

---

## Identity mappings

Some entities are the same person / band / label across platforms, but no
external database records this.  The mapping system lets you declare these
links explicitly.

### File locations

| Priority | Path |
|---|---|
| 1 (base) | `metadatarr/data/mappings.toml` — shipped with the package |
| 2 (user) | `$XDG_CONFIG_HOME/metadatarr/mappings.toml` (default: `~/.config/metadatarr/mappings.toml`) |

The user file is loaded after the package file.  If an entry in the user file
shares any identifier with a package entry of the same kind, they are merged
(more IDs added to the existing entry).  Otherwise a new entry is added.

### File format

```toml
# ~/.config/metadatarr/mappings.toml

[[artist]]
name = "Acidkid / Piratech"          # display label — not used for matching
soundcloud_artist_url = "https://soundcloud.com/acidkid"
bandcamp_artist_url   = "https://piratech.bandcamp.com/"

[[artist]]
name = "Some Band"
bandcamp_band_id        = "12345678"
soundcloud_user_id      = "987654"
musicbrainz_artist      = "some-mbid-uuid"

[[album]]
name = "OK Computer"
musicbrainz_release_group = "some-mbid"
bandcamp_album_id         = "99999999"
```

Supported section types mirror `EntityKind`:
`artist`, `album`, `label`, `channel`, `actor`, `director`, `producer`,
`composer`, `writer`, `narrator`, `host`, `author`, `other`.

Keys inside a section can be:
- Any first-class `ExternalIds` field name (`musicbrainz_artist`,
  `metal_archives_band`, `tmdb_person`, …)
- Any `extra.*` key a provider emits (`bandcamp_band_id`,
  `soundcloud_user_id`, `youtube_music_artist_browse_id`, `bandcamp_artist_url`, …)
- `name` — human label, ignored during matching

URL values are normalised (lowercase host, trailing slash stripped) so
`https://piratech.bandcamp.com/` and `https://piratech.bandcamp.com` are
treated identically.

### How matching works

When `consolidate()` accepts a provider match it calls
`apply_mappings(kind, external_ids)` for every `EntityKind`.  The store
checks every `(key, value)` pair in the incoming `ExternalIds` against its
reverse index.  On a hit the mapping entry's identifiers are merged into the
result (the live result takes precedence over mapping values, so a freshly
fetched numeric ID is never overwritten by a stale mapping).

This means: if a Bandcamp result carries `bandcamp_artist_url` that matches
a mapping entry which also declares `soundcloud_user_id`, the consolidated
`ExternalIds` will contain both — even though Bandcamp knows nothing about
SoundCloud.

#### Probabilistic mappings (`score`)

Hand-curated TOML entries default to `score=1.0`. Programmatically-added
entries can declare a lower score — useful for auto-generated links you
don't want to apply unconditionally:

```python
from metadatarr.resolve.mappings import add_mapping, get_store
from metadatarr.resolve.entities import EntityKind
from metadatarr.resolve.external_ids import ExternalIds

add_mapping(EntityKind.ARTIST,
            {"musicbrainz_artist": "abc-mbid", "wikidata": "Q12345"},
            name="Auto-linked", score=0.6)

# Apply only high-confidence mappings:
out = get_store().apply(EntityKind.ARTIST,
                        ExternalIds(musicbrainz_artist="abc-mbid"),
                        min_score=0.8)
# `out` is unchanged — the score=0.6 entry was below the gate.
```

### Using the mapping store directly

```python
from metadatarr.resolve.mappings import get_store, reload, apply_mappings, add_mapping
from metadatarr.resolve.entities import EntityKind
from metadatarr.resolve.external_ids import ExternalIds

# Enrich a known set of ids
ids = ExternalIds(extra={"bandcamp_artist_url": "https://piratech.bandcamp.com/"})
enriched = apply_mappings(EntityKind.ARTIST, ids)
print(enriched.extra.get("soundcloud_user_id"))  # → "987654" if declared

# Register a mapping at runtime (process-lifetime only; not persisted to file)
add_mapping(
    EntityKind.ARTIST,
    {
        "soundcloud_artist_url": "https://soundcloud.com/acidkid",
        "bandcamp_artist_url":   "https://piratech.bandcamp.com/",
    },
    name="Acidkid / Piratech",
)

# Reload from files (discards any runtime add_mapping() calls)
reload()

# Inspect the store
store = get_store()
print(len(store))  # number of mapping entries
```

### Adding package-level mappings

The curated package file lives at `/metadatarr/data/mappings.toml`.  Entries
there ship with every install and serve as a community-maintained link
registry.  Send a PR if you know a cross-platform identity that isn't already
there — the bar for inclusion is simply that the link is publicly verifiable
(e.g. the artist's own bio mentions both profiles).

---

## Entity records

If you want to persist entity data across runs, use the `EntitySidecar` +
mutation helpers instead of (or alongside) raw `ExternalIds` dicts:

```python
from metadatarr.resolve.entities import (
    EntitySidecar, EntityKind, ProviderEntity,
    upsert_entity, attach_work, entities_by_kind,
)
from metadatarr.resolve.external_ids import ExternalIds

sidecar = EntitySidecar()

# After resolving a match that returned artist relations:
for entity in match.relations.get(EntityKind.ARTIST, []):
    eid = upsert_entity(sidecar, entity)
    attach_work(sidecar, eid, work_id="my-work-123")

# Query
artists = entities_by_kind(sidecar, EntityKind.ARTIST)
```

`upsert_entity()` is idempotent: two providers referencing the same external
ID always collapse to the same `EntityRecord`. Aliases accumulate;
`ExternalIds` fields are merged field-wise.

The entity id seed includes the provider's declared `role` when there's
no external id to anchor on — so two namesakes appearing as DIRECTOR and
WRITER respectively don't collapse into one entity. When an external id
*is* present it always wins (same person, two hats).

### Persistence + reverse index

`metadatarr.resolve.sidecar` adds atomic JSON load/save and an O(1)
reverse-lookup index over the entities dict:

```python
from metadatarr.resolve.sidecar import save, load, build_index
from metadatarr.resolve.entities import EntityKind

save(sidecar, "entities.json")           # tempfile + os.replace; safe on crash
sidecar = load("entities.json")          # missing path → empty EntitySidecar

idx = build_index(sidecar)

# Lookup by any external id (first-class field name OR `extra` key):
eid = idx.find_by_external_id(EntityKind.ARTIST, "musicbrainz_artist", "mbid")

# Lookup by name OR alias (normalised — case / punctuation collapsed):
candidates = idx.find_by_name(EntityKind.ARTIST, "daft  punk!")
```

Rebuild the index after batch updates; it's a snapshot, not a live view.

---

## YouTube vs YouTube Music

These are two separate providers with completely different semantics.

**`youtube`** — regular YouTube.  A video ID identifies a single upload, not
a song.  The same song has thousands of uploads; none is authoritative.  This
provider only emits `EntityKind.CHANNEL` relations (never `ARTIST` or
`ALBUM`), and refuses `Medium.MUSIC` lookups entirely.  Use it for content
that is *original to YouTube* — vlogs, essays, original podcasts, etc.

**`youtube_music`** — YouTube Music.  This catalog has proper *entity*
records: stable `browseId` values for artists (`UCxxx…`) and albums
(`MPREb_xxx`).  Those are canonical music IDs safe to treat as
cross-references.  Track-level results carry `youtube_music_video_id`
(distinct from `youtube_video_id`) to make the conceptual boundary explicit.

---

## Writing a custom provider

```python
from typing import Optional
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityKind, ProviderEntity
from metadatarr.resolve.external_ids import ExternalIds
from metadatarr.resolve.signals import Medium, Signals


class MyProvider(MetadataProvider):
    name = "my_provider"
    media = {Medium.MUSIC}

    def is_available(self) -> bool:
        return True  # or check for env vars / optional deps

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None

        # ... call your API ...
        result = my_api.search(signals.title)
        if not result:
            return None

        return ProviderMatch(
            provider=self.name,
            confidence=0.7,          # 0–1; how much to trust this result
            signals=Signals(
                title=result["title"],
                artist=result["artist"],
                year=result.get("year"),
                medium=Medium.MUSIC,
            ),
            external_ids=ExternalIds(
                musicbrainz_artist=result.get("mbid"),
                extra={"my_platform_id": str(result["id"])},
            ),
            relations={
                EntityKind.ARTIST: [ProviderEntity(
                    kind=EntityKind.ARTIST,
                    name=result["artist"],
                    external_ids=ExternalIds(extra={"my_platform_id": str(result["id"])}),
                )],
            },
        )


register(MyProvider())
```

### Provider guidelines

- **Guard optional imports** — wrap `import my_lib` in `try/except ImportError`
  inside `__init__`, set `self._available = False` on failure, return it from
  `is_available()`.
- **Canonical IDs only** — only store IDs that are stable.  Numeric platform
  IDs are stable; URL slugs are not (platforms let users rename them).  If
  you only have a URL, store it as a `*_url` extra key so the consumer can
  link back, but don't use it as a canonical entity identifier.
- **Refuse wrong mediums** — check `signals.medium` and return `None` if your
  source doesn't cover it.  This prevents spurious cross-domain matches.
- **Confidence** — a rough guide: 0.9 for exact-ID lookups, 0.7 for
  strong-signal search, 0.5–0.6 for fuzzy search or unreliable sources.
- **Don't swallow exceptions silently in production** — the `LOG.warning`
  pattern is fine for network errors; don't silently drop programming errors.
