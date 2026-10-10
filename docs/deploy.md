# Deploying (Docker)

Homelab-oriented: a single container, open by default, with optional API
keys and rate limiting for an instance reachable from outside the LAN.

```bash
cd deploy
docker compose up -d --build
curl http://localhost:8000/healthz
```

Open `http://localhost:8000/` for the WebUI — see [`docs/webui.md`](webui.md) for a
tour of the pages.

The image installs from source (`pip install ".[server]"` against the repo
checkout), and a few first-party dependencies are still pinned to
`git+https://...@dev` refs until they're published to PyPI. That's why the
Dockerfile installs `git` at build time (see `deploy/Dockerfile`) — it's a
build-time-only dependency, not something the running container needs.

## Environment variables

All optional — every keyless provider works out of the box.

| Variable | Purpose |
| --- | --- |
| `TMDB_API_KEY` | enables the TMDB provider |
| `TVDB_API_KEY` | enables the TheTVDB provider |
| `DISCOGS_TOKEN` | enables the Discogs provider |
| `METADATARR_HTTP_CACHE` | directory for the on-disk HTTP response cache (default: unset = no cache) |
| `METADATARR_HTTP_CACHE_TTL` | cache TTL in seconds (default 86400; `0` = no expiry); also the `max-age` the API sends |
| `METADATARR_API_KEYS` | comma-separated API keys; unset = no authentication |
| `METADATARR_AUTH_EXEMPT` | comma-separated CIDRs that need no key and are not rate limited; `private` = loopback, RFC 1918, 100.64.0.0/10 (Tailscale), IPv6 ULA and link-local |
| `METADATARR_RATE_LIMIT` | requests per minute per API key (per client address when keys are off); unset or `0` = no limit |
| `METADATARR_RATE_LIMIT_BURST` | requests allowed at once before the limit applies (default: the per-minute rate) |
| `METADATARR_AUDIO_ROOTS` | directories (separated by `:`) that `/api/v1/identify/audio?path=` may read; unset = uploads only |
| `METADATARR_MAX_UPLOAD_BYTES` | largest audio upload accepted (default 50 MiB) |

Set them in `deploy/docker-compose.yml` (commented placeholders are there)
or via `docker run -e ...`.

## Volumes

- `/data` — HTTP cache (`METADATARR_HTTP_CACHE=/data/http-cache`).
- `/config` — `XDG_CONFIG_HOME`, so your mappings overlay lives at
  `/config/metadatarr/mappings.toml` inside the container. Mount a host file
  there to add cross-platform identity assertions without rebuilding the
  image.

## HTTP API

Every route is under `/api/v1`; the interactive schema is at `/docs` and
`/openapi.json` (its version is the package version). The routes that
predate versioning (`/resolve`, `/candidates`, `/enrich`, `/providers`,
`/healthz`, `/stats`, `/identify/audio`) also answer at their unversioned
paths.

| Route | Purpose |
| --- | --- |
| `POST /api/v1/resolve` | resolve one `Signals` bag |
| `GET /api/v1/resolve?title=…&year=…&medium=…` | the same from query parameters named after `Signals` fields; answers `304` to a matching `If-None-Match` |
| `POST /api/v1/resolve/batch` | `{"items": [Signals, …]}`, at most 100; results come back in request order, each `{"index", "ok", "result"}` or `{"index", "ok": false, "error"}` |
| `POST /api/v1/candidates` | every provider's match, ranked, without consolidation |
| `POST /api/v1/enrich` | derive more ids from the ids given |
| `POST /api/v1/identify/video` | `{"filename", "duration"?, "size"?, "hints"?}`: parse the file name as a library scan would (only its last path component; the server opens nothing), fill `runtime` from `duration` (seconds), apply `hints` (`Signals` fields), then resolve |
| `POST /api/v1/identify/audio` | audio fingerprint, then resolve: a multipart `file` upload, or `?path=` naming a file under `METADATARR_AUDIO_ROOTS` (any other path is refused with `403`) |

Lookup responses carry an `ETag` and `Cache-Control: max-age` equal to the
provider cache TTL (`private` when API keys are on). A result produced while
a provider failed is sent with `no-cache`. Add `?refresh=1` to skip the
provider and HTTP caches for one request; the fresh result replaces the
cached one.

## Access control

The server is open unless `METADATARR_API_KEYS` is set. With keys, every
route except `/healthz`, `/api/v1/healthz` and `/static/` needs an
`X-Api-Key` header or an `apikey` query parameter, and answers `401`
without one. Clients in `METADATARR_AUTH_EXEMPT` need no key.

`METADATARR_RATE_LIMIT` enables a token bucket per key (per client address
when keys are off); a client over its limit gets `429` with `Retry-After`
in seconds.

The client address is the TCP peer. Behind a reverse proxy every request
comes from the proxy, so an exempt network that contains the proxy exempts
everyone, and an address-keyed limit is shared by all clients: use API keys
there. The same holds for Docker's published ports, where the peer is the
bridge gateway.
