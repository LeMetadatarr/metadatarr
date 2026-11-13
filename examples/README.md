# Examples

Small end-to-end scripts. Each one exercises a single client family or the
resolve framework. Scripts marked **Network** make real HTTP requests — run
them when you want to sanity-check a live API. Scripts marked **Offline** need
no network and no auth.

Providers route on a third axis — `playback_type` (`AUDIO`, `VIDEO`, `TEXT`).
Pass `Signals(playback_type=PlaybackType.AUDIO)` to restrict dispatch to audio-only
providers; omitting `playback_type` (or setting it to `None`) keeps all-provider
fan-out. See [`docs/resolve.md`](../docs/resolve.md#three-axis-routing-gate).

Run any of them directly:

```bash
python examples/library_cut_dedup.py   # no network needed
python examples/fanedit_discovery.py   # needs network access
```

---

## Streams

| Script | Network | What it does |
| ------------------------------- | :-----: | ------------ |
| `streams_music.py`  | Yes | Resolve a track → collect every playable URL across SoundCloud, Bandcamp, YouTube, YouTube Music |
| `streams_video.py`          | Yes | Resolve a film or podcast episode → get a YouTube URL ready for `mpv` / `yt-dlp` |
| `channel_to_metadata.py`    | Yes | Walk a YouTube channel (Mosfilm) → link each upload to IMDb/TMDB/Wikidata via mapping-first then title-resolve fallback |
| `streams_radio.py`  | No  | Declare internet radio stations in `mappings.toml` → build a typed play queue via `ExternalIds.streams` |

---

## Client demos

| Script                          | Network | What it does |
| ------------------------------- | :-----: | ------------ |
| `arr_search.py`                 | Yes | Sonarr / Radarr / Lidarr search via Servarr proxies |
| `books.py`                      | Yes | OpenLibrary, BookInfo, Anna's Archive book lookups |
| `music.py`                      | Yes | AudioDB artist + album lookup |
| `video.py`                      | Yes | TVmaze show / season / cast lookup |
| `resolve_movie.py`              | Yes | Cross-source resolve walkthrough for a movie |
| `resolve_artist_merge.py`       | Yes | Per-provider attribution for music across several bands |
| `resolve_mapping_demo.py`       | Yes | Cross-platform track resolution from a single artist mapping |
| `cross_provider_search.py`      | Yes | `search()` fan-out — ranked candidate union across every active provider |

---

## Physical media

| Script                          | Network | User story |
| ------------------------------- | :-----: | ---------- |
| `physical_disc_verify.py`       | Yes | "I have a Blu-ray — which cut is it and which regional edition?" Uses DVDCompare cut runtimes and per-release data to identify a disc and build its canonical Signals hash |
| `alien_trilogy_physical_and_fanedits.py` | Yes | Full walkthrough of the Alien trilogy: cut comparison, dvdcompare regional releases, IFDB fanedit enumeration |
| `discogs_music_video.py`        | Yes | "I collect music video LaserDiscs and soundtrack vinyl." Discogs for its correct domain: concert film search with `search_video()`, NTSC/PAL format details, identifiers, community stats, master pressings, `MediaType.MUSIC_VIDEO` in Signals |

---

## Fanedits & release variants

These examples all use `include_variants=True`. `pyfanedit` is a core
dependency, so no extra install step is needed.

| Script                             | Network | User story |
| ---------------------------------- | :-----: | ---------- |
| `fanedit_discovery.py`             | Yes | "What fanedits exist across a director's filmography?" — resolves a list of films and ranks them by IFDB activity |
| `fanedit_picker.py`                | Yes | "Help me pick one to watch tonight" — fetches full detail for all fanedits of a film, filters by type (FanFix / FanMix / …), ranks by rating, shows cuts summary |
| `resolve_variants_movie.py`        | Yes | Resolve a movie and collect all IFDB fanedits in one call |
| `resolve_fanedit_by_imdb.py`       | Yes | Two paths: full resolve vs direct `list_variants()` from a known IMDb id |
| `variant_fanedit_detail.py`        | Yes | Fetch full `FaneditDetail` (synopsis, cuts, ratings) after collecting fanedit ids |
| `variant_resolve_with_without.py`  | Yes | Side-by-side resolve with/without `include_variants` — shows cost and additive nature |
| `resolve_variants_album.py`        | Yes | Resolve an album + expand release-group → regional pressings via MusicBrainz |

---

## Signal layer & library tools (no network)

| Script                             | User story |
| ---------------------------------- | ---------- |
| `library_cut_dedup.py`             | "De-dupe my library: same cut = same hash, different cuts stay separate" — parses filenames, buckets by `signal_hash`, marks best-quality file as keeper and flags real duplicates for deletion |
| `variant_signals.py`               | `VariantKind`, `compare()`, `merged()`, `signal_hash()` — pure signal-layer walkthrough |
| `variant_disambiguation_cuts.py`   | Same title, two cuts (theatrical vs extended): separate hashes, conflict detection |
| `variant_source_format.py`         | `source_format` keeps 4K, Blu-ray, Vinyl rips as distinct canonical records |
| `variant_album_editions.py`        | Standard vs deluxe editions; free-text `edition` for non-enum pressings |
| `variant_regional_film.py`         | `region` vs `country`: JP regional pressing ≠ US release even with same `variant_kind` |
| `variant_provider_registry.py`     | Inspect which active providers override `list_variants()` before calling resolve |
| `variant_custom_provider.py`       | Subclass `MetadataProvider` to plug in a local JSON fanedit catalogue |
