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
from mediavocab import Signals, MediaType

signals = Signals(
    title="Sankarihauta",
    artist="Moonsorrow",
    year=2003,
    medium=MediaType.MUSIC,
)
```

All fields are optional: pass as much or as little as you have.  The more
context you provide, the better providers can filter their results and the
more aggressively `consolidate()` can reject mismatches.

| Field | Type | Purpose |
|---|---|---|
| `title` | `str` | Work title |
| `artist` | `str` | Primary artist / director / author |
| `year` | `int` | Release year |
| `runtime` | `float` | Duration in seconds |

| Field | Type | Purpose |
|---|---|---|
| `medium` | `Medium` | Content category (see below) |
| `language` | `str` | ISO 639-1 code |
| `country` | `str` | ISO 3166-1 alpha-2 code |
| `season` | `int` | TV season number (TV episodes only) |

| Field | Type | Purpose |
|---|---|---|
| `episode` | `int` | TV episode number (TV episodes only) |
| `variant_kind` | `VariantKind` | Cut / edition discriminator (see below) |
| `edition` | `str` | Free-text edition name (e.g. `"25th Anniversary"`) |
| `region` | `str` | ISO 3166-1 alpha-2, release territory (distinct from work-origin `country`) |

| Field | Type | Purpose |
|---|---|---|
| `source_format` | `str` | Physical / digital format (e.g. `"4K"`, `"Blu-ray"`, `"Vinyl"`) |
| `include_variants` | `bool` | When `True`, `resolve()` fans out to variant-aware providers and populates `result.variants` |

`Signals`: `mediavocab/models/signals.py`

**`MediaType` values**: `MUSIC`, `MUSIC_VIDEO`, `MOVIE`, `EPISODIC_SERIES`, `TV`, `PODCAST`, `BOOK`, `COMIC`, `AUDIOBOOK`, `AUDIO_DRAMA`, `RADIO`, `GAME`, `INTERACTIVE_FICTION`, `SOUND_EFFECT`, `AMBIENT_SOUNDS`, `PLAYLIST`, `GENERIC`, `NOT_MEDIA`.

`EPISODIC_SERIES` is used for on-demand series (Sonarr/TVmaze/streaming shows/Blu-ray box sets).
`TV` is reserved for live linear / IPTV broadcast, analogous to `RADIO`.
`MUSIC_VIDEO` covers concert films, official music videos, and live performances on physical video media (LaserDisc, VHS, DVD). It is the medium for Discogs music-video searches.  `MediaType`: `mediavocab`

#### VariantKind

`VariantKind`: `mediavocab`

A string enum that classifies cuts and editions for conflict detection.
`compare()` treats two bags as conflicting on `variant_kind` only when both
sides set it and the values differ, an absent value is never a conflict.

| Value | Applies to |
|---|---|
| `THEATRICAL` | Film: original theatrical cut |
| `DIRECTORS` | Film: director's cut |
| `EXTENDED` | Film or album: extended version |
| `FANEDIT` | Film: fan-edited cut |

| Value | Applies to |
|---|---|
| `COLORIZED` | Film: colourised version of B&W original |
| `UPSCALED` | Film: AI/manual upscale |
| `STANDARD` | Album: standard edition |
| `DELUXE` | Album: deluxe edition |

| Value | Applies to |
|---|---|
| `BONUS_TRACKS` | Album: bonus-tracks edition |
| `REISSUE` | Album: reissue |
| `COMPILATION` | Album: compilation |
| `REGIONAL` | Film or album: territory-specific release |

| Value | Applies to |
|---|---|
| `REMASTERED` | Film or album: remastered |
| `OTHER` | Anything else |
### Three-axis routing gate

Provider dispatch is controlled by three independent `ClassVar` sets on every
`MetadataProvider` subclass (mediavocab spec axiom 13). A provider is asked
only when **all three** axes pass:

```
(no media declared        OR signals.medium    in provider.media)
AND
(no playback_type declared OR signals.playback_type in provider.playback_type)
AND
(no genre_filter declared OR provider.genre_filter ∩ signals.content_genres)
```

`MetadataProvider.matches()`: `metadatarr/resolve/base.py:122`

**`media`**: which `MediaType` values the provider serves. Setting `medium`
on `Signals` routes around unrelated catalogues: a `MUSIC` lookup never
touches TVmaze, a `MOVIE` lookup never touches Bandcamp.

**`playback_type`**: which `PlaybackType` values (`AUDIO`, `VIDEO`, `TEXT`,
`INTERACTIVE`, `UNKNOWN`). This axis lets you route a `MediaType.GENERIC`
query to audio-only or video-only providers without inventing a fake
media type. An empty `playback_type` set means the provider accepts all modalities.

**`genre_filter`**: genre tags from `mediavocab.taxonomy.genre`. Used for
Anime/Manga gating (rather than a fake `MediaType.ANIME`, per axiom 2).

```python
from metadatarr.resolve.base import active_providers
from mediavocab import MediaType, PlaybackType

# Without modality: all GENERIC-capable providers (youtube, wikidata, discogs, …)
generic = active_providers(medium=MediaType.GENERIC)

# With modality: only AUDIO providers that also accept GENERIC
# (discogs, youtube_music would be excluded as they declare MUSIC not GENERIC)
audio_only = [
    p for p in generic
    if not p.playback_type or PlaybackType.AUDIO in p.playback_type
]
```

For `resolve()` callers, pass `playback_type` directly on `Signals`:

```python
from metadatarr.resolve.base import resolve
from mediavocab import Signals, MediaType, PlaybackType

# "play something by Moonsorrow": route to AUDIO providers only
result = resolve(Signals(
    title="Moonsorrow",
    medium=MediaType.GENERIC,
    playback_type=PlaybackType.AUDIO,
))
# → routes to musicbrainz, audiodb, bandcamp, soundcloud, metal_archives,
#   youtube_music, librivox, discogs: NOT to tvmaze, bluray_com, etc.

# "watch Attack on Titan": VIDEO providers for an episodic series
result = resolve(Signals(
    title="Attack on Titan",
    medium=MediaType.EPISODIC_SERIES,
    playback_type=PlaybackType.VIDEO,
))
# → routes to tvmaze, anilist, jikan_anime, skyhook, wikidata
```

`Signals.playback_type`: `mediavocab/models/signals.py`

#### Title comparison

Titles are matched fuzzily after a normalisation pass that:

1. Folds Unicode diacritics via NFKD (so `Café` and `cafe` compare equal,
   `Pokémon` and `Pokemon` are the same work, etc.), base characters of
   any script are kept intact.
2. Strips parenthetical qualifiers, "feat. …" / "ft. …" segments, and
   collapses punctuation/whitespace to single spaces.

Two titles agree when their `difflib` ratio after normalisation is at
least `TITLE_FUZZY_MIN` (default `0.92`).

#### Runtime tolerance

`compare()` uses `RUNTIME_TOLERANCE_BY_MEDIUM_S` (movies ±120 s, TV ±30 s,
music ±3 s, music\_video ±30 s, books `0`, podcast ±30 s, other ±5 s) when
both sides declare a `medium`. Falls back to `RUNTIME_TOLERANCE_S` (5 s)
when neither side does.  `RUNTIME_TOLERANCE_BY_MEDIUM_S`: `mediavocab`

#### `match_quality()`

`metadatarr.resolve.match_quality(local, candidate)` returns a `[0.0, 1.0]`
score combining title fuzzy ratio, year agreement, and medium agreement.
Built-in providers multiply their base confidence by this score so a
strong upstream that returned the *wrong* record doesn't outvote a weaker
upstream that returned the *right* one.

### ExternalIds

The output of a successful lookup is an `ExternalIds` instance.  It has
typed typed fields for every well-known platform ID, plus an `extra`
dict for everything else:

```python
from mediavocab import ExternalIds

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

| Field | Type | Platform |
|---|---|---|
| `musicbrainz_artist` | `str` | MusicBrainz |
| `imdb` | `str` | IMDb (tt-id) |
| `tmdb_movie` | `int` | TMDB |
| `tmdb_tv` | `int` | TMDB |

| Field | Type | Platform |
|---|---|---|
| `tvdb` | `int` | TVDB |
| `isbn_10` / `isbn_13` | `str` | Books |
| `olid` | `str` | OpenLibrary |
| `goodreads` | `str` | Goodreads |

| Field | Type | Platform |
|---|---|---|
| `wikidata` | `str` | Wikidata (Q-id) |
| `tmdb_person` | `int` | TMDB person |
| `imdb_person` | `str` | IMDb person (nm-id) |
| `metal_archives_band` | `int` | Encyclopaedia Metallum |

| Field | Type | Platform |
|---|---|---|
| `metal_archives_release` | `int` | Encyclopaedia Metallum |
| `metal_archives_song` | `str` | Encyclopaedia Metallum (alphanumeric lyrics-id form returned by song search) |
| `metal_archives_label` | `int` | Encyclopaedia Metallum |
| `metal_archives_artist` | `int` | Encyclopaedia Metallum |

| Field | Type | Platform |
|---|---|---|
| `fanedit_id` | `int` | IFDB (fanedit.org) WordPress post ID |
| `derived_from_imdb` | `str` | Parent IMDb tt-id, set on records that *are* variants of another work |
| `discogs_release` | `int` | Discogs numeric release ID |
| `bluray_com_id` | `int` | blu-ray.com movie page ID |

| Field | Type | Platform |
|---|---|---|
| `dvdcompare_id` | `str` | dvdcompare.net edition slug |

`ExternalIds`: `mediavocab/models/__init__.py`

Everything a provider emits that doesn't have a typed slot lands in
`extra` as `str → str`.  Common extra keys:

| Key | Platform |
|---|---|
| `bandcamp_band_id` | Bandcamp numeric artist id |
| `bandcamp_track_id` | Bandcamp numeric track id |
| `bandcamp_album_id` | Bandcamp numeric album id |
| `bandcamp_*_url` | Bandcamp page URLs (metadata, not canonical ids) |

| Key | Platform |
|---|---|
| `soundcloud_user_id` | SoundCloud numeric user id |
| `soundcloud_track_id` | SoundCloud numeric track id |
| `soundcloud_*_url` | SoundCloud page URLs |
| `youtube_video_id` | YouTube upload id (11 chars) |

| Key | Platform |
|---|---|
| `youtube_channel_id` | YouTube channel id (`UCxxx` or `@handle`) |
| `youtube_music_video_id` | YouTube Music track id |
| `youtube_music_artist_browse_id` | YouTube Music artist entity id |
| `youtube_music_album_browse_id` | YouTube Music album entity id |

| Key | Platform |
|---|---|
| `youtube_music_playlist_id` | YouTube Music album playlist id |
| `youtube_content_type` | Classifier hint from tutubo |
| `hanime_video_id` | hanime.tv numeric video id (canonical) |
| `hanime_brand_id` | hanime.tv numeric studio id (canonical, anchors the `STUDIO` entity) |

| Key | Platform |
|---|---|
| `hanime_franchise_id` | hanime.tv numeric series id (canonical) |
| `hanime_slug` / `hanime_url` | hanime.tv watch slug / URL (link-back, slug is renameable) |

#### ISBN normalisation

`ExternalIds` runs an `@model_validator(mode="after")` that:

1. Strips formatting (hyphens / spaces / non-digits, preserving a trailing
   `X` check digit) from `isbn_10` and `isbn_13`
2. Back-fills the sibling form when only one is given (978-prefixed
   ISBN-13s have an ISBN-10 representation, non-978 13s do not).

So `ExternalIds(isbn_10="0-261-10328-8")` ends up with both
`isbn_10="0261103288"` and `isbn_13="9780261103283"`. Two providers that
disagree on representation merge cleanly.

The conversion helpers are public:
`mediavocab.text.isbn10_to_13`,
`isbn13_to_10`, and `normalize_isbn`.

#### Merge semantics

`ExternalIds.merge(other)` is **first-writer-wins**: fields already set
on `self` are preserved, `other` only fills in empty slots. The same
applies inside `extra`. Combine with `consolidate()`'s confidence
ordering and the strongest provider's IDs anchor the result.

### Entities

Providers don't just return IDs for the work itself: they also return
**relations**: typed pointers to related entities (the artist, the album the
track is on, the director, the publisher, …).

The entity layer uses two separate enums with distinct concerns:

- `EntityKind`: structural shape of the underlying entity record, re-exported from
  `mediavocab.EntityKind`: `PERSON`, `GROUP`, `ORGANISATION`, `SERIES`, `DEVICE`, `OTHER`.
- `EntityRole`: relational role in the context of a specific work, the key type for
  `ProviderMatch.relations` and `ResolveResult.relations`. Values: `ACTOR`, `VOICE_ACTOR`,
  `DIRECTOR`, `PRODUCER`, `COMPOSER`, `WRITER`, `NARRATOR`, `HOST`, `AUTHOR`, `ARTIST`,
  `LABEL`, `CHANNEL`, `STUDIO`, `OTHER`. Work-shaped emissions (release variants)
  live on `ProviderMatch.variants` rather than as relation roles.

`EntityKind` is re-exported from `mediavocab`. `EntityRole`: `metadatarr/resolve/entities.py:57`

```python
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds

# A provider match may include:
match.relations = {
    EntityRole.ARTIST: [ProviderEntity(
        role=EntityRole.ARTIST,
        name="Moonsorrow",
        external_ids=ExternalIds(extra={"bandcamp_band_id": "12345678"}),
    )],
}

# Release variants live on ProviderMatch.variants:
match.variants = [ProviderEntity(role=EntityRole.OTHER, name="...", ...)]
```

`ProviderEntity.kind` is auto-derived from `role.to_mediavocab_kind()` when omitted: `ARTIST` → `EntityKind.GROUP`, `DIRECTOR` → `EntityKind.PERSON`,
`LABEL` → `EntityKind.ORGANISATION`, etc. Pass `kind` explicitly to override.
`ProviderEntity`: `metadatarr/resolve/entities.py:281`

Release variants (specific releases / cuts of a work: individual MusicBrainz
releases within a release-group, or fanedit.org entries) are emitted on
`ProviderMatch.variants` and surfaced on `result.variants` when
`include_variants=True`.

Entities get their own stable IDs via `allocate_entity_id()`, which derives a
deterministic SHA1 from the strongest known external ID (MusicBrainz > Metal
Archives > Wikidata > platform numeric id > …).  Two providers referencing
the same MusicBrainz artist will always produce the same entity ID.
`allocate_entity_id()`: `metadatarr/resolve/entities.py:260`

---

## Providers

Providers self-register on import. All providers listed below are bundled in
the core install: every first-party scraper (pyfanedit, pymetal, tutubo,
py_bandcamp, nuvem_de_som) is a core dependency. The only optional install
extra is `[test]`.

| Name | Source | Media | Modality | Notes |
|---|---|---|---|---|
| `skyhook` | Servarr proxies | movie / episodic_series / music / book | universal | no env vars needed: `metadatarr/resolve/providers/servarr_proxy.py:32` |
| `musicbrainz` | MusicBrainz API | music | AUDIO | artist, release, recording IDs |
| `audiodb` | TheAudioDB | music | AUDIO | free public key |
| `tvmaze` | TVmaze public API | episodic_series | VIDEO | no auth, `MediaType.EPISODIC_SERIES` only |

| Name | Source | Media | Modality | Notes |
|---|---|---|---|---|
| `anilist` | AniList GraphQL | movie / episodic_series / comic | VIDEO + TEXT | |
| `jikan_anime` | Jikan (MyAnimeList) | movie / episodic_series | VIDEO | |
| `jikan_manga` | Jikan (MyAnimeList) | comic | TEXT | |
| `librivox` | LibriVox API | audiobook | AUDIO | |

| Name | Source | Media | Modality | Notes |
|---|---|---|---|---|
| `apple_podcasts` | Apple Podcasts search | podcast / audio_drama | AUDIO | |
| `wikidata` | Wikidata API | all | universal | Q-id + cross-references |
| `bandcamp` | Bandcamp | music | AUDIO | `py_bandcamp` core dep |
| `soundcloud` | SoundCloud | music | AUDIO | `nuvem_de_som` core dep |

| Name | Source | Media | Modality | Notes |
|---|---|---|---|---|
| `youtube_music` | YouTube Music | music | AUDIO | `tutubo` core dep, browseId entity records |
| `youtube` | YouTube | movie / episodic_series / podcast / generic | universal | `tutubo` core dep, channel IDs only, refuses `MUSIC` |
| `metal_archives` | Encyclopaedia Metallum | music | AUDIO | `pymetal` core dep |
| `pyfanedit` | fanedit.org / IFDB | movie | VIDEO | variant-only: `lookup()` returns `None`, `list_variants()` calls `FaneditClient.search_by_original_title()`: `metadatarr/resolve/providers/pyfanedit.py:41` |

| Name | Source | Media | Modality | Notes |
|---|---|---|---|---|
| `bluray_com` | blu-ray.com | movie | VIDEO | HTML scraper |
| `dvdcompare` | dvdcompare.net | movie | VIDEO | HTML scraper |
| `discogs` | Discogs REST API | music / music_video / generic | AUDIO + VIDEO | 25 req/min unauthenticated, set `DISCOGS_TOKEN` for 60 req/min |
| `openlibrary` | OpenLibrary | book | TEXT | auto-registered |

| Name | Source | Media | Modality | Notes |
|---|---|---|---|---|
| `annas_archive` | Anna's Archive | book | TEXT | auto-registered |

### Multiple candidates per provider

Each provider exposes two lookup methods:

- `lookup(signals) -> Optional[ProviderMatch]`: the single best match
  (used by direct callers).
- `lookup_candidates(signals) -> List[ProviderMatch]`: up to N ranked
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
from mediavocab import MediaType, PlaybackType

all_providers()                              # {name: provider}: every registered provider
active_providers()                           # those whose is_available() is True
active_providers(medium=MediaType.MUSIC)     # further filtered to music-capable providers

# Modality filtering is manual: active_providers() doesn't take a modality kwarg:
audio = [p for p in active_providers() if not p.playback_type or PlaybackType.AUDIO in p.playback_type]
```

---

## Running a lookup

### Simple: `resolve()`

```python
import metadatarr.resolve.providers          # triggers provider self-registration
from metadatarr.resolve.base import resolve
from mediavocab import Signals, MediaType

result = resolve(Signals(title="Inception", medium=MediaType.MOVIE))
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

### Raw candidate list: `candidates()`

When you want every provider's vote individually instead of one merged record: a disambiguation UI, a "did you mean…" list, or your own merge policy: call
`candidates()`. It runs the same concurrent, cached fan-out as `resolve()` but
returns the ranked `List[ProviderMatch]` without consolidating.

```python
from metadatarr.resolve import candidates
from mediavocab import Signals, MediaType

for m in candidates(Signals(title="Inception", medium=MediaType.MOVIE))[:5]:
    print(m.provider, m.confidence, m.external_ids.tmdb_movie)
```

`resolve()` is exactly `consolidate(candidates(signals), signals)`. `search()`
is a thin alias for `candidates()`, prefer `candidates()`, which names its return
value (ranked candidate matches) more clearly.

### Manual: `consolidate()`

For cases where you control which providers run or want to supply pre-fetched
matches:

```python
from metadatarr.resolve.base import active_providers, consolidate, ProviderMatch
from mediavocab import Signals, MediaType

signals = Signals(title="Inception", medium=MediaType.MOVIE)
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
| `signals` | `Signals \| None` | Merged signals from accepted matches, `None` on irreconcilable conflict |
| `external_ids` | `ExternalIds` | Merged IDs from accepted matches, enriched by mappings |
| `accepted` | `List[ProviderMatch]` | Matches that agreed with local signals and each other (sorted by confidence desc) |
| `dropped` | `List[ProviderMatch]` | Matches dropped for conflicting with local signals or the running consolidation |

| Field | Type | Description |
|---|---|---|
| `conflicts` | `List[ResolutionConflict]` | Per-drop diagnostic: which provider clashed, with what, on which fields |
| `relations` | `Dict[EntityRole, List[ProviderEntity]]` | Contribution entities collected from accepted matches |
| `variants` | `List[ProviderEntity]` | Release-variant entities, populated only when `signals.include_variants=True` |

`ResolveResult`: `metadatarr/resolve/base.py:63`

#### Variant fan-out

When `signals.include_variants=True`, `resolve()` runs a second pass after
consolidation. It calls `list_variants(result.external_ids, signals)` on
every active provider whose `media` set includes the requested medium.
Results are de-duplicated by `fanedit_id` > `musicbrainz_release` > `name`
(first seen wins) and stored in `result.variants`.

```python
from metadatarr.resolve.base import resolve
from metadatarr.resolve.entities import EntityRole
from mediavocab import Signals, MediaType

result = resolve(Signals(
    title="Inception",
    medium=MediaType.MOVIE,
    include_variants=True,
))
for entity in result.variants:
    print(entity.name, entity.external_ids.fanedit_id)
```

`resolve()` variant fan-out: `metadatarr/resolve/base.py:387`

`consolidate()` consumes matches **highest-confidence first**, so the
strongest provider anchors the consensus regardless of input order.

### Conflict detection

`compare(a, b)` returns a list of `SignalConflict` describing every field
where `a` and `b` disagree beyond tolerance:

- **Title**: fuzzy ratio must be ≥ `TITLE_FUZZY_MIN` (`0.92`).
- **Artist**: fuzzy ratio must be ≥ `ARTIST_FUZZY_MIN` (`0.90`).
- **Year**: must agree within `YEAR_TOLERANCE` (±1 year).
- **Runtime**: per-medium tolerance (movies ±120 s, TV ±30 s, music ±3 s,
  books `0`, podcast ±30 s, other ±5 s, see
  `RUNTIME_TOLERANCE_BY_MEDIUM_S`).
- **Medium** / **country** / **language**: exact match when both set.
- **Season** / **episode**: exact match when both set.
- **Variant kind**: exact match when both set, absent on either side is not a conflict.
- **Region**: case-insensitive exact match when both set.
- **Source format**: case-insensitive exact match when both set.

A match is dropped if it conflicts with `local`. The consolidation marks
the result `signals=None` if two already-accepted matches conflict with
each other.

`ResolutionConflict` lets the caller introspect *why* something was
dropped without re-running `compare()`:

```python
from metadatarr.resolve import resolve, MediaType, Signals

result = resolve(Signals(title="Inception", year=2010, medium=MediaType.MOVIE))
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
| 1 (base) | `metadatarr/data/mappings.toml`: shipped with the package |
| 2 (user) | `$XDG_CONFIG_HOME/metadatarr/mappings.toml` (default: `~/.config/metadatarr/mappings.toml`) |

The user file is loaded after the package file.  If an entry in the user file
shares any identifier with a package entry of the same kind, they are merged
(more IDs added to the existing entry).  Otherwise a new entry is added.

### File format

```toml
# ~/.config/metadatarr/mappings.toml

[[artist]]
name = "Acidkid / Piratech"          # display label: not used for matching
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

Supported section types correspond to `EntityRole` values:
`actor`, `voice_actor`, `director`, `producer`, `composer`, `writer`,
`narrator`, `host`, `author`, `artist`, `label`, `channel`, `studio`, `other`.

`EntityRole`: `metadatarr/resolve/entities.py:57`

Keys inside a section can be:
- Any typed `ExternalIds` field name (`musicbrainz_artist`,
  `metal_archives_band`, `tmdb_person`, …)
- Any `extra.*` key a provider emits (`bandcamp_band_id`,
  `soundcloud_user_id`, `youtube_music_artist_browse_id`, `bandcamp_artist_url`, …)
- `name`: human label, ignored during matching

URL values are normalised (lowercase host, trailing slash stripped) so
`https://piratech.bandcamp.com/` and `https://piratech.bandcamp.com` are
treated identically.

### How matching works

When `consolidate()` accepts a provider match it calls
`apply_mappings(role, external_ids)` for every `EntityRole`.  The store
checks every `(key, value)` pair in the incoming `ExternalIds` against its
reverse index.  On a hit the mapping entry's identifiers are merged into the
result (the live result takes precedence over mapping values, so a freshly
fetched numeric ID is never overwritten by a stale mapping).

This means: if a Bandcamp result carries `bandcamp_artist_url` that matches
a mapping entry which also declares `soundcloud_user_id`, the consolidated
`ExternalIds` will contain both: even though Bandcamp knows nothing about
SoundCloud.

#### Probabilistic mappings (`score`)

Hand-curated TOML entries default to `score=1.0`. Programmatically-added
entries can declare a lower score: useful for auto-generated links you
don't want to apply unconditionally:

```python
from metadatarr.resolve.mappings import add_mapping, get_store
from metadatarr.resolve.entities import EntityRole
from mediavocab.models import ExternalIds

add_mapping(EntityRole.ARTIST,
            {"musicbrainz_artist": "abc-mbid", "wikidata": "Q12345"},
            name="Auto-linked", score=0.6)

# Apply only high-confidence mappings:
out = get_store().apply(EntityRole.ARTIST,
                        ExternalIds(musicbrainz_artist="abc-mbid"),
                        min_score=0.8)
# `out` is unchanged: the score=0.6 entry was below the gate.
```

### Using the mapping store directly

```python
from metadatarr.resolve.mappings import get_store, reload, apply_mappings, add_mapping
from metadatarr.resolve.entities import EntityRole
from mediavocab.models import ExternalIds

# Enrich a known set of ids
ids = ExternalIds(extra={"bandcamp_artist_url": "https://piratech.bandcamp.com/"})
enriched = apply_mappings(EntityRole.ARTIST, ids)
print(enriched.extra.get("soundcloud_user_id"))  # → "987654" if declared

# Register a mapping at runtime (process-lifetime only; not persisted to file)
add_mapping(
    EntityRole.ARTIST,
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
there: the bar for inclusion is simply that the link is publicly verifiable
(e.g. the artist's own bio mentions both profiles).

---

## Entity records

If you want to persist entity data across runs, use the `EntitySidecar` +
mutation helpers instead of (or alongside) raw `ExternalIds` dicts:

```python
from metadatarr.resolve.entities import (
    EntitySidecar, EntityRole, ProviderEntity,
    upsert_entity, attach_work, entities_by_role,
)
from mediavocab.models import ExternalIds

sidecar = EntitySidecar()

# After resolving a match that returned artist relations:
for entity in match.relations.get(EntityRole.ARTIST, []):
    eid = upsert_entity(sidecar, entity)
    attach_work(sidecar, eid, work_id="my-work-123")

# Query
artists = entities_by_role(sidecar, EntityRole.ARTIST)
```

`upsert_entity()` is idempotent: two providers referencing the same external
ID always collapse to the same `EntityRecord`. Aliases accumulate
`ExternalIds` fields are merged field-wise.

The entity id seed includes the provider's declared `role` when there's
no external id to anchor on: so two namesakes appearing as DIRECTOR and
WRITER respectively don't collapse into one entity. When an external id
*is* present it always wins (same person, two hats).

### Persistence + reverse index

`metadatarr.resolve.sidecar` adds atomic JSON load/save and an O(1)
reverse-lookup index over the entities dict:

```python
from metadatarr.resolve.sidecar import save, load, build_index
from metadatarr.resolve.entities import EntityRole

save(sidecar, "entities.json")           # tempfile + os.replace; safe on crash
sidecar = load("entities.json")          # missing path → empty EntitySidecar

idx = build_index(sidecar)

# Lookup by any external id (typed field name OR `extra` key):
eid = idx.find_by_external_id(EntityRole.ARTIST, "musicbrainz_artist", "mbid")

# Lookup by name OR alias (normalised: case / punctuation collapsed):
candidates = idx.find_by_name(EntityRole.ARTIST, "daft  punk!")
```

Rebuild the index after batch updates, it's a snapshot, not a live view.

---

## YouTube vs YouTube Music

These are two separate providers with completely different semantics.

**`youtube`**: regular YouTube.  A video ID identifies a single upload, not
a song.  The same song has thousands of uploads, none is authoritative.  This
provider only emits `EntityRole.CHANNEL` relations (never `ARTIST` or
`LABEL`), and refuses `MediaType.MUSIC` lookups entirely.  Use it for content
that is *original to YouTube*: vlogs, essays, original podcasts, etc.

**`youtube_music`**: YouTube Music.  This catalog has proper *entity*
records: stable `browseId` values for artists (`UCxxx…`) and albums
(`MPREb_xxx`).  Those are canonical music IDs safe to treat as
cross-references.  Track-level results carry `youtube_music_video_id`
(distinct from `youtube_video_id`) to make the conceptual boundary explicit.

---

## Writing a custom provider

```python
from typing import Optional
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab import Signals, MediaType, PlaybackType


class MyProvider(MetadataProvider):
    name = "my_provider"
    media = {MediaType.MUSIC}
    playback_type = {PlaybackType.AUDIO}   # omit or leave empty to accept all modalities

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
            confidence=0.7,          # 0 to 1; how much to trust this result
            signals=Signals(
                title=result["title"],
                artist=result["artist"],
                year=result.get("year"),
                medium=MediaType.MUSIC,
            ),
            external_ids=ExternalIds(
                musicbrainz_artist=result.get("mbid"),
                extra={"my_platform_id": str(result["id"])},
            ),
            relations={
                EntityRole.ARTIST: [ProviderEntity(
                    role=EntityRole.ARTIST,
                    name=result["artist"],
                    external_ids=ExternalIds(extra={"my_platform_id": str(result["id"])}),
                )],
            },
        )


register(MyProvider())
```

### Provider guidelines

- **Guard optional imports**: wrap `import my_lib` in `try/except ImportError`
  inside `__init__`, set `self._available = False` on failure, return it from
  `is_available()`.
- **Canonical IDs only**: only store IDs that are stable.  Numeric platform
  IDs are stable, URL slugs are not (platforms let users rename them).  If
  you only have a URL, store it as a `*_url` extra key so the consumer can
  link back, but don't use it as a canonical entity identifier.
- **Refuse wrong mediums**: check `signals.medium` and return `None` if your
  source doesn't cover it.  This prevents spurious cross-domain matches.
- **Confidence**: a rough guide: 0.9 for exact-ID lookups, 0.7 for
  strong-signal search, 0.5 to 0.6 for fuzzy search or unreliable sources.
- **Don't swallow exceptions silently in production**: the `LOG.warning`
  pattern is fine for network errors, don't silently drop programming errors.

---
[← Physical disc guide](physical-disc.md) · [Home](README.md) · [Provider catalogue →](providers.md)
