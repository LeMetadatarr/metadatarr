# Deploying (Docker)

Homelab-oriented: single container, no auth, meant to sit behind your own
reverse proxy on a trusted LAN.

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
| `METADATARR_HTTP_CACHE_TTL` | cache TTL in seconds |

Set them in `deploy/docker-compose.yml` (commented placeholders are there)
or via `docker run -e ...`.

## Volumes

- `/data` — HTTP cache (`METADATARR_HTTP_CACHE=/data/http-cache`).
- `/config` — `XDG_CONFIG_HOME`, so your mappings overlay lives at
  `/config/metadatarr/mappings.toml` inside the container. Mount a host file
  there to add cross-platform identity assertions without rebuilding the
  image.

## Security note

There is **no built-in authentication**. This is meant for a single-tenant
homelab setup: put it behind a reverse proxy (Caddy, Traefik, nginx) with
your own auth layer if it needs to be reachable outside your LAN.
