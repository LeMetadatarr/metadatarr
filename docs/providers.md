# Provider catalogue

Providers self-register on `import metadatarr.resolve`. Each one declares a
`name` and a set of `media` it covers, and gates itself behind an
`is_available()` check — missing API keys, missing optional dependencies,
or unreachable services silently disable the provider rather than crashing
your call.

Use `metadatarr.resolve.all_providers()` to inspect what's registered, and
`active_providers(medium=…)` to see what's actually usable right now.

## Built-in providers

| Name              | Media                  | Config / dependency                                   |
| ----------------- | ---------------------- | ----------------------------------------------------- |
| `metadatarr`      | movie / TV / music / book | none — wraps the bundled Servarr metadata-proxy clients (`skyhook.sonarr.tv`, `radarrapi.servarr.com`, `api.lidarr.audio`) |
| `musicbrainz`     | music                  | none (public API, polite rate-limit)                  |
| `audiodb`         | music                  | none (free public key)                                |
| `tvmaze`          | TV                     | none                                                  |
| `wikidata`        | movie / TV / music / book / podcast | none                                     |
| `youtube`         | movie / TV / podcast / other | optional dep `tutubo` (`pip install metadatarr[youtube]`) |
| `youtube_music`   | music                  | optional dep `tutubo` (`pip install metadatarr[youtube]`) |
| `bandcamp`        | music                  | optional dep `py_bandcamp` (`pip install metadatarr[bandcamp]`) |
| `soundcloud`      | music                  | optional dep `nuvem_de_som` (`pip install metadatarr[soundcloud]`) |
| `metal_archives`  | music                  | optional dep `pymetal` (`pip install metadatarr[metal_archives]`) |
| `pyfanedit`       | movie                  | hard dep (`pyfanedit` is in core `dependencies`); variant-only — `lookup()` always returns `None`; `list_variants()` calls `FaneditClient.search_by_original_title()` — `metadatarr/resolve/providers/pyfanedit.py:61` |
| `bluray_com`      | movie / TV             | none — HTML scraper, no auth; confidence 0.65×match_quality; writes `bluray_com_id` to `ExternalIds` and `bluray_com_url`, `bluray_com_cover` to `extra` |
| `dvdcompare`      | movie / TV             | none — HTML scraper, no auth; confidence 0.60×match_quality; infers `VariantKind` from `version` text; writes `dvdcompare_id`, `imdb` to `ExternalIds` and `dvdcompare_url`, `dvdcompare_version`, `dvdcompare_version_diff` to `extra` |
| `discogs`         | music / music\_video / other | none — public REST API, 25 req/min unauthenticated; set `DISCOGS_TOKEN` env var for 60 req/min; `lookup()` calls `search_video()` for `MUSIC_VIDEO` or video source formats, `search()` for audio formats — `metadatarr/resolve/providers/discogs.py:61`; confidence 0.70×match_quality; writes `discogs_release` to `ExternalIds` and `discogs_url`, `discogs_label`, `discogs_catno`, `discogs_cover` to `extra`; implements `enrich()` to fetch full label/image data when `discogs_release` id is already known |

## Inspecting at runtime

```python
from metadatarr.resolve import all_providers, active_providers, Medium

for name, provider in all_providers().items():
    flag = "ON " if provider.is_available() else "off"
    print(f"  [{flag}] {name}")

for p in active_providers(medium=Medium.MUSIC):
    print(p.name)
```

## Adding your own

```python
from typing import Optional
from metadatarr.resolve import (
    ExternalIds, Medium, MetadataProvider,
    ProviderMatch, Signals, register,
)

class MyProvider(MetadataProvider):
    name = "my_provider"
    media = {Medium.MOVIE}

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
