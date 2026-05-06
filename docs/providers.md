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

| Name              | Media                            | Notes                                                  |
| ----------------- | -------------------------------- | ------------------------------------------------------ |
| `metadatarr`      | movie / episodic_series / music / book | Servarr metadata-proxy clients (`skyhook.sonarr.tv`, `radarrapi.servarr.com`, `api.lidarr.audio`) + OpenLibrary |
| `musicbrainz`     | music                            | Public API — polite rate-limit                         |
| `audiodb`         | music                            | Free public key, no auth                               |
| `tvmaze`          | episodic_series                  | `MediaType.EPISODIC_SERIES` — on-demand series only; not live TV |
| `anilist`         | movie / episodic_series / comic  | AniList GraphQL API; core dep                          |
| `jikan_anime`     | movie / episodic_series          | Jikan (MyAnimeList); core dep                          |
| `jikan_manga`     | comic                            | Jikan (MyAnimeList); core dep                          |
| `librivox`        | audiobook                        | LibriVox API; core dep                                 |
| `apple_podcasts`  | podcast / audio_drama            | Apple Podcasts search API; core dep                    |
| `wikidata`        | movie / episodic_series / music / book / podcast | none                              |
| `youtube`         | movie / episodic_series / podcast / other | core dep (`tutubo`); emits channel IDs only; refuses `MUSIC` lookups |
| `youtube_music`   | music                            | core dep (`tutubo`); stable browseId entity records    |
| `bandcamp`        | music                            | core dep (`py_bandcamp`)                               |
| `soundcloud`      | music                            | core dep (`nuvem_de_som`)                              |
| `metal_archives`  | music                            | core dep (`pymetal`)                                   |
| `pyfanedit`       | movie                            | core dep; variant-only — `lookup()` always returns `None`; `list_variants()` calls `FaneditClient.search_by_original_title()` — `metadatarr/resolve/providers/pyfanedit.py:61` |
| `bluray_com`      | movie                            | HTML scraper, no auth; confidence 0.65×match_quality; writes `bluray_com_id` to `ExternalIds` and `bluray_com_url`, `bluray_com_cover` to `extra` |
| `dvdcompare`      | movie                            | HTML scraper, no auth; confidence 0.60×match_quality; infers `VariantKind` from `version` text; writes `dvdcompare_id`, `imdb` to `ExternalIds` |
| `discogs`         | music / music\_video / other     | Public REST API, 25 req/min unauthenticated; set `DISCOGS_TOKEN` for 60 req/min; `lookup()` calls `search_video()` for `MUSIC_VIDEO`, `search()` for audio — `metadatarr/resolve/providers/discogs.py:61`; confidence 0.70×match_quality |

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
