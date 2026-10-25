# ArrMetadataClient

Wraps the three public Servarr metadata proxies: **Skyhook** (Sonarr / TV),
**Servarr Movie API** (Radarr / movies), and **MusicInfo** (Lidarr / music).
These are the same servers Sonarr/Radarr/Lidarr hit by default: no auth,
no quota documented, but be polite.

```python
from metadatarr import ArrMetadataClient
client = ArrMetadataClient()
```

## Endpoints

| Domain | Method | Returns | Upstream |
|---|---|---|---|
| TV | `search_series(term)` | `list[SonarrSeries]` | `GET skyhook.sonarr.tv/v1/tvdb/search/en/?term=` |
| TV | `get_series_info(tvdb_id)` | `SonarrSeries \| None` | `GET skyhook.sonarr.tv/v1/tvdb/shows/en/{id}` |
| Movies | `search_movie(term)` | `list[RadarrMovie]` | `GET radarrapi.servarr.com/v1/search?q=` |
| Movies | `get_movie_info(tmdb_id)` | `RadarrMovie \| None` | `GET radarrapi.servarr.com/v1/movie/{id}` |

| Domain | Method | Returns | Upstream |
|---|---|---|---|
| Music | `search_artist(term)` | `list[LidarrArtist]` | `GET api.lidarr.audio/api/v0.4/search?query=&type=artist` |
| Music | `get_artist_info(mbid)` | `LidarrArtist \| None` | `GET api.lidarr.audio/api/v0.4/artist/{mbid}` |

## TV (Sonarr / Skyhook)

```python
results = client.search_series("Severance")
for s in results:
    print(s.tvdb_id, s.title, s.year, s.overview[:60] if s.overview else "")

# Fetch full record once you have the TVDB ID
detail = client.get_series_info(371980)
```

`SonarrSeries` fields: `title`, `tvdb_id`, `year`, `overview`. Anything else
returned by Skyhook is ignored: extend the model if you need more (see
[Extending models](../models.md#extending-models)).

## Movies (Radarr / Servarr Movie API)

```python
movies = client.search_movie("Inception")
for m in movies:
    print(m.tmdb_id, m.title, m.year)

inception = client.get_movie_info(27205)
print(inception.overview)
```

`RadarrMovie` fields: `title`, `tmdb_id`, `year`, `overview`.

## Music (Lidarr / MusicInfo)

```python
artists = client.search_artist("Daft Punk")
for a in artists:
    print(a.id, a.name, (a.overview or "")[:80])
```

`LidarrArtist` fields: `id` (MusicBrainz ID, a string UUID), `name`, `title`
(alias of name), `overview`.

> Warning: Lidarr's response can wrap the artist inside an `Artist` envelope or
> return it flat depending on the endpoint. The model uses `AliasPath` to
> handle both: you always read `artist.name` regardless.

## Customising

```python
client = ArrMetadataClient(user_agent="my-app/2.0 (+https://example.org)")
```

Pass a meaningful `User-Agent`. The Servarr operators run these as a public
service for the *arr ecosystem, identifying yourself helps them spot abuse
versus legitimate use.

The base URLs are public attributes: `client.endpoints["sonarr"]` etc.: and
you can monkey-patch them if a provider migrates or you self-host a mirror.

## Internals

All requests go through `_get(url, params)`:

```python
response = requests.get(url, headers=self.headers, params=params, timeout=10)
response.raise_for_status()
return response.json()
```

On exception it returns `[]` for endpoints whose URL contains `"search"` and
`{}` otherwise. The list/dict choice means model validation can run uniformly
without extra null checks at the call site.

## Caveats

- **No retries.** A flaky DNS lookup will give you an empty result. Wrap with
  `tenacity` or your retry library of choice if you care.
- **TVDB-only for series, TMDB-only for movies.** If you need IMDb, MAL, AniDB
  or other IDs you'll need to chain to those services yourself.
- **Lidarr's MusicInfo is the most volatile** of the three, expect occasional
  schema drift. Open an issue if you see a real upstream change that the
  `AliasChoices` doesn't already cover.

---
[← Getting started](../getting-started.md) · [Home](../README.md) · [BookInfoClient →](bookinfo.md)
