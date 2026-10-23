# HTTP transport

Every request this package issues goes through a single shared session built by
`metadatarr.transport.make_session`. The session mounts one adapter that adds
two behaviours on top of plain `requests`:

- **Per-host rate limiting** — requests to throttled hosts are spaced by a
  minimum interval, coordinated process-wide so the concurrent resolver
  fan-out cannot burst a single host through several providers that share it.
- **Opt-in disk caching** — GET/HEAD responses with status `200` are stored on
  disk when `METADATARR_HTTP_CACHE` is set, using the standard library only.

```python
from metadatarr.transport import make_session

session = make_session()
resp = session.get("https://example.com/api")
```

## Scope

Rate limiting and disk caching apply to HTTP that this package issues directly
— the typed clients in `metadatarr.client` and the in-tree providers under
`metadatarr/resolve/providers/`. Providers whose network access happens inside
sibling libraries reach the network through those libraries' own sessions and
are not covered by this transport.

## Per-host rate limits

Intervals are minimum seconds between requests to a host, keyed by
`urlsplit(url).netloc.lower()`. Unlisted hosts are not throttled.

| Host | Interval | Source |
|---|---|---|
| `musicbrainz.org` | 1.0 s | [MusicBrainz API rate limiting](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting) — 1 req/s |
| `api.discogs.com` | 1.0 s | [Discogs API](https://www.discogs.com/developers) — 60 req/min authenticated |
| `www.wikidata.org` | 0.5 s | [Wikidata data access](https://www.wikidata.org/wiki/Wikidata:Data_access) — courteous 2 req/s |

A caller can register or tighten a host's interval:

```python
session = make_session(rate_limits={"api.discogs.com": 2.5})
```

The limiter is shared across sessions, so a stricter interval registered by one
caller applies to every session for that host.

## Disk cache

Set `METADATARR_HTTP_CACHE` to enable caching. GET and HEAD responses with
status `200` are stored; other methods and non-200 responses pass through.

| Variable | Meaning |
|---|---|
| `METADATARR_HTTP_CACHE` | `1` (or any non-empty value) enables caching. A path value (e.g. `/tmp/my_cache`) sets the cache directory; otherwise `~/.cache/metadatarr/http` is used. |
| `METADATARR_HTTP_CACHE_TTL` | Entry lifetime in seconds. Defaults to `86400` (24 h). `0` caches indefinitely. |

```bash
METADATARR_HTTP_CACHE=1 python examples/resolve_movie.py
METADATARR_HTTP_CACHE=/tmp/my_cache METADATARR_HTTP_CACHE_TTL=3600 python examples/resolve_movie.py
```

Maintenance helpers:

```python
from metadatarr import transport

transport.info()   # {'enabled', 'path', 'ttl', 'entries', 'size_bytes'}
transport.clear()  # delete cached response files, return the count removed
```

## Out of scope

Asynchronous transport, automatic retries with backoff, and honouring
`Retry-After` headers are possible extensions to the adapter.
