# Provider catalogue

Providers self-register on `import metadatarr.resolve`. Each one declares a
`name` and a set of `media` it covers, and gates itself behind an
`is_available()` check — missing API keys, missing optional dependencies,
or unreachable services silently disable the provider rather than crashing
your call.

Use `metadatarr.resolve.all_providers()` to inspect what's registered, and
`active_providers(medium=…)` to see what's actually usable right now.

## Built-in providers

All dependencies listed below are core (bundled) — no optional extras required.

Routing is **three-axis**: `media`, `modality`, and `genre_filter`. A provider
is dispatched only when every declared axis matches the caller's `Signals`.
An empty set on any axis means "accept all" for that axis.
`MetadataProvider.matches()` — `metadatarr/resolve/base.py:118`

| Name              | Media                            | Modality          | Notes                                                  |
| ----------------- | -------------------------------- | ----------------- | ------------------------------------------------------ |
| `skyhook`         | movie / episodic_series / music / book | universal (empty) | Servarr metadata-proxy clients (`skyhook.sonarr.tv`, `radarrapi.servarr.com`, `api.lidarr.audio`) — `metadatarr/resolve/providers/servarr_proxy.py:33` |
| `musicbrainz`     | music                            | AUDIO             | Public API — polite rate-limit — `metadatarr/resolve/providers/musicbrainz.py:21` |
| `audiodb`         | music                            | AUDIO             | Free public key, no auth — `metadatarr/resolve/providers/audiodb.py:32` |
| `tvmaze`          | episodic_series                  | VIDEO             | `MediaType.EPISODIC_SERIES` — on-demand series only; not live TV — `metadatarr/resolve/providers/tvmaze.py:26` |
| `anilist`         | movie / episodic_series / comic  | VIDEO + TEXT      | AniList GraphQL API; core dep — `metadatarr/resolve/providers/anilist.py:69` |
| `jikan_anime`     | movie / episodic_series          | VIDEO             | Jikan (MyAnimeList); core dep — `metadatarr/resolve/providers/jikan.py:43` |
| `jikan_manga`     | comic                            | TEXT              | Jikan (MyAnimeList); core dep — `metadatarr/resolve/providers/jikan.py:115` |
| `librivox`        | audiobook                        | AUDIO             | LibriVox API; core dep — `metadatarr/resolve/providers/librivox.py:31` |
| `apple_podcasts`  | podcast / audio_drama            | AUDIO             | Apple Podcasts search API; core dep — `metadatarr/resolve/providers/podcast_index.py:30` |
| `wikidata`        | movie / episodic_series / music / book / podcast | universal (empty) | Q-id + cross-references — `metadatarr/resolve/providers/wikidata.py:44` |
| `youtube`         | movie / episodic_series / podcast / generic | universal (empty) | core dep (`tutubo`); emits channel IDs only; refuses `MUSIC` lookups — `metadatarr/resolve/providers/youtube.py:48` |
| `youtube_music`   | music                            | AUDIO             | core dep (`tutubo`); stable browseId entity records — `metadatarr/resolve/providers/youtube_music.py:82` |
| `bandcamp`        | music                            | AUDIO             | core dep (`py_bandcamp`) — `metadatarr/resolve/providers/bandcamp.py:104` |
| `soundcloud`      | music                            | AUDIO             | core dep (`nuvem_de_som`) — `metadatarr/resolve/providers/soundcloud.py:47` |
| `metal_archives`  | music                            | AUDIO             | core dep (`pymetal`) — `metadatarr/resolve/providers/metal_archives.py:30` |
| `pyfanedit`       | movie                            | VIDEO             | core dep; variant-only — `lookup()` always returns `None`; `list_variants()` calls `FaneditClient.search_by_original_title()` — `metadatarr/resolve/providers/pyfanedit.py:42` |
| `bluray_com`      | movie                            | VIDEO             | HTML scraper, no auth; confidence 0.65×match_quality; writes `bluray_com_id` to `ExternalIds` and `bluray_com_url`, `bluray_com_cover` to `extra` — `metadatarr/resolve/providers/bluray_com.py:25` |
| `dvdcompare`      | movie                            | VIDEO             | HTML scraper, no auth; confidence 0.60×match_quality; infers `VariantKind` from `version` text; writes `dvdcompare_id`, `imdb` to `ExternalIds` — `metadatarr/resolve/providers/dvdcompare.py:91` |
| `discogs`         | music / music\_video / generic   | AUDIO + VIDEO     | Public REST API, 25 req/min unauthenticated; set `DISCOGS_TOKEN` for 60 req/min; `lookup()` calls `search_video()` for `MUSIC_VIDEO`, `search()` for audio — `metadatarr/resolve/providers/discogs.py:46` |
| `openlibrary`     | book                             | TEXT              | Auto-registered; OpenLibrary ISBN/work lookup — `metadatarr/resolve/providers/openlibrary.py:25` |
| `annas_archive`   | book                             | TEXT              | Auto-registered; HTML scrape of Anna's Archive mirrors — `metadatarr/resolve/providers/annas_archive.py:29` |
| `hanime`          | movie / episodic_series          | VIDEO             | hentai-anime; optional dep (`pyhanime`); **genre-gated** to `adult`+`anime` queries; stable numeric IDs (`hanime_video_id`, `hanime_brand_id`, `hanime_franchise_id`) in `extra`; emits `STUDIO` relation — `metadatarr/resolve/providers/hanime.py` |

## Inspecting at runtime

```python
from metadatarr.resolve import all_providers, active_providers, MediaType

for name, provider in all_providers().items():
    flag = "ON " if provider.is_available() else "off"
    print(f"  [{flag}] {name}")

for p in active_providers(medium=MediaType.MUSIC):
    print(p.name)
```

## Adding your own

```python
from typing import Optional
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from mediavocab import MediaType, Signals
from mediavocab.models import ExternalIds

class MyProvider(MetadataProvider):
    name = "my_provider"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        # ...do your lookup, populate ProviderMatch...
        return ProviderMatch(
            provider=self.name,
            confidence=0.8,
            signals=signals,
            external_ids=ExternalIds(),
        )

register(MyProvider())
```
