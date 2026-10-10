# SPDX-License-Identifier: Apache-2.0
"""JSON API routes for the metadatarr server.

Mounted onto a FastAPI ``app`` by :func:`register_routes`. Bodies / responses
use pydantic models from :mod:`metadatarr.server.models` plus the resolver's
own :class:`~metadatarr.resolve.base.ResolveResult` /
:class:`~metadatarr.resolve.base.ProviderMatch`.

Every route lives under ``/api/v1``. The routes that predate versioning are
also served at their unversioned paths (``/resolve``, ``/healthz``, ...) as
aliases of the same handlers, hidden from the OpenAPI schema.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

# Safe at module level: this module is only ever imported by
# metadatarr.server.app.create_app(), which calls _require_fastapi() first.
# Needed as a real (non-forward-ref) name so FastAPI/pydantic can resolve the
# `UploadFile` parameter annotation on identify_audio_endpoint below — a
# purely-local `from fastapi import ...` inside register_routes() leaves the
# name unresolvable under `from __future__ import annotations`.
from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

# Triggers built-in provider self-registration as a side effect of import.
import metadatarr.resolve.providers  # noqa: F401

from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals

from metadatarr.resolve.base import (
    ProviderMatch,
    ResolveResult,
    all_providers,
    candidates as run_candidates,
    enrich as run_enrich,
    resolve as run_resolve,
)
from metadatarr.library import LocalMediaFile, _SXXEXX_RE, extract_embedded_ids, extract_signals
from metadatarr.server.config import ServerConfig
from metadatarr.server.models import (
    AudioIdentifyResponse,
    BatchItemResult,
    BatchResolveRequest,
    BatchResolveResponse,
    EnrichRequest,
    HealthResponse,
    ProviderInfo,
    plugin_infos,
    ProvidersResponse,
    ResolveRequest,
    StatsResponse,
    VideoIdentifyRequest,
    VideoIdentifyResponse,
)
from metadatarr.server.security import PathNotAllowed, resolve_allowed_path
from metadatarr.transport import bypass_cache, info as cache_info
from metadatarr.version import __version__

LOG = logging.getLogger(__name__)


def _provider_counts() -> "tuple[int, int]":
    """Return ``(available, total)`` from the registry, tolerating a
    provider whose ``is_available()`` itself raises (treated as unavailable
    rather than failing the whole count)."""
    registry = all_providers()
    available = 0
    for p in registry.values():
        try:
            if p.is_available():
                available += 1
        except Exception:  # pragma: no cover - defensive
            pass
    return available, len(registry)


API_PREFIX = "/api/v1"

# Items of one batch resolved at the same time; each item fans out to its
# own ``max_workers`` provider threads.
BATCH_CONCURRENCY = 8

# ``max-age`` sent when the provider cache never expires.
_MAX_AGE_NO_EXPIRY = 365 * 24 * 3600

# Query parameters of ``GET /api/v1/resolve`` that are not Signals fields.
_RESOLVE_QUERY_CONTROL = {"refresh", "apikey", "max_workers"}


def _max_age() -> int:
    ttl = cache_info()["ttl"]
    return int(ttl) if ttl else _MAX_AGE_NO_EXPIRY


def _etag(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def _etag_matches(header: str, etag: str) -> bool:
    for tag in header.split(","):
        tag = tag.strip()
        if tag == "*" or tag.removeprefix("W/") == etag:
            return True
    return False


def _cached_response(request: Request, payload: Any, *, config: ServerConfig,
                     degraded: bool = False) -> Response:
    """JSON response carrying an ``ETag`` and a ``Cache-Control`` lifetime
    equal to the provider cache TTL.

    A result produced while a provider failed (``degraded``) is sent with
    ``no-cache`` so clients revalidate it. A ``GET``/``HEAD`` whose
    ``If-None-Match`` names the current ETag gets ``304 Not Modified``.
    """
    body = json.dumps(jsonable_encoder(payload), separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    etag = _etag(body)
    scope = "private" if config.auth_enabled else "public"
    cache_control = "no-cache" if degraded else f"{scope}, max-age={_max_age()}"
    headers = {"ETag": etag, "Cache-Control": cache_control}
    inm = request.headers.get("if-none-match")
    if request.method in ("GET", "HEAD") and inm and _etag_matches(inm, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "item"
        parts.append(f"{loc}: {err.get('msg')}")
    return "; ".join(parts)


def _video_basename(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if name in ("", ".", "..") or "\x00" in name:
        raise HTTPException(status_code=422, detail="filename has no usable name")
    return name


def register_routes(app, templates, config: Optional[ServerConfig] = None) -> None:
    config = config or ServerConfig()
    resolves_total = 0
    resolves_lock = threading.Lock()

    def _count(n: int = 1) -> None:
        nonlocal resolves_total
        with resolves_lock:
            resolves_total += n

    # ``shared`` holds the routes that also answer at their unversioned path.
    shared = APIRouter()
    v1 = APIRouter()

    @shared.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        # A static 200 proves only that the process is up; a metadatarr
        # deployment with zero available providers is otherwise invisible
        # to monitoring (no DB to fail against), so surface the counts.
        available, total = _provider_counts()
        return HealthResponse(
            version=__version__,
            providers_available=available,
            providers_total=total,
        )

    @shared.get("/stats", response_model=StatsResponse)
    def stats() -> StatsResponse:
        cache = cache_info()
        with resolves_lock:
            total = resolves_total
        return StatsResponse(
            resolves_total=total,
            cache_enabled=cache["enabled"],
            cache_entries=cache["entries"] if cache["enabled"] else 0,
            cache_bytes=cache["size_bytes"] if cache["enabled"] else 0,
        )

    @shared.get("/providers", response_model=ProvidersResponse)
    def providers() -> ProvidersResponse:
        registry = all_providers()
        infos: List[ProviderInfo] = []
        for name, p in sorted(registry.items()):
            try:
                avail = bool(p.is_available())
            except Exception:
                avail = False
            infos.append(ProviderInfo(
                name=name,
                available=avail,
                media=sorted(getattr(m, "value", str(m)) for m in (p.media or set())),
                modality=sorted(getattr(m, "value", str(m)) for m in (p.playback_type or set())),
                genre_filter=sorted(p.genre_filter or set()),
            ))
        return ProvidersResponse(
            total=len(infos),
            active=sum(1 for i in infos if i.available),
            providers=infos,
            plugins=plugin_infos(),
        )

    def _resolve(signals: Signals, max_workers: int, refresh: bool) -> ResolveResult:
        _count()
        try:
            with bypass_cache(refresh):
                return run_resolve(signals, max_workers=max_workers)
        except Exception:  # pragma: no cover - defensive
            LOG.exception("resolve failed")
            raise HTTPException(
                status_code=500, detail="internal error during resolve") from None

    @shared.post("/resolve", response_model=ResolveResult)
    def resolve_endpoint(request: Request, body: ResolveRequest,
                         refresh: bool = False) -> Response:
        payload = body.model_dump(exclude={"max_workers"})
        result = _resolve(Signals(**payload), body.max_workers, refresh)
        return _cached_response(request, result, config=config,
                                degraded=bool(result.provider_errors))

    @v1.get("/resolve", response_model=ResolveResult)
    def resolve_get_endpoint(request: Request, refresh: bool = False,
                             max_workers: int = 8) -> Response:
        """Resolve from query parameters named after ``Signals`` fields
        (``?title=Inception&year=2010&medium=movie``); list fields such as
        ``content_genres`` take the parameter repeated. Cacheable by
        intermediaries and conditional on ``If-None-Match``."""
        if not 1 <= max_workers <= 32:
            raise HTTPException(status_code=422, detail="max_workers must be 1..32")
        fields: Dict[str, Any] = {}
        for name in request.query_params.keys():
            if name in _RESOLVE_QUERY_CONTROL:
                continue
            values = request.query_params.getlist(name)
            field = Signals.model_fields.get(name)
            is_list = field is not None and getattr(field.annotation, "__origin__", None) is list
            fields[name] = values if is_list else values[-1]
        try:
            signals = Signals(**fields)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=_validation_message(e)) from None
        result = _resolve(signals, max_workers, refresh)
        return _cached_response(request, result, config=config,
                                degraded=bool(result.provider_errors))

    @v1.post("/resolve/batch", response_model=BatchResolveResponse)
    def resolve_batch_endpoint(request: Request, body: BatchResolveRequest,
                               refresh: bool = False) -> Response:
        """Resolve up to 100 signal bags; results come back in request order.
        An item that fails validation or resolution carries ``ok: false``
        and an ``error`` instead of failing the batch."""

        def _one(index: int, item: Dict[str, Any]) -> BatchItemResult:
            try:
                signals = Signals(**item)
            except ValidationError as e:
                return BatchItemResult(index=index, ok=False, error=_validation_message(e))
            except TypeError as e:
                return BatchItemResult(index=index, ok=False, error=str(e))
            _count()
            try:
                with bypass_cache(refresh):
                    result = run_resolve(signals, max_workers=body.max_workers)
            except Exception as e:
                LOG.exception("batch item %d failed", index)
                return BatchItemResult(index=index, ok=False,
                                       error=f"{e.__class__.__name__}: resolve failed")
            return BatchItemResult(index=index, ok=True, result=result)

        workers = min(BATCH_CONCURRENCY, len(body.items))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(contextvars.copy_context().run, _one, i, item)
                       for i, item in enumerate(body.items)]
            results = [f.result() for f in futures]
        degraded = any(not r.ok or (r.result and r.result.provider_errors) for r in results)
        return _cached_response(request, BatchResolveResponse(results=results),
                                config=config, degraded=degraded)

    @shared.post("/candidates", response_model=List[ProviderMatch])
    def candidates_endpoint(request: Request, body: ResolveRequest,
                            refresh: bool = False) -> Response:
        payload = body.model_dump(exclude={"max_workers"})
        signals = Signals(**payload)
        try:
            with bypass_cache(refresh):
                matches = run_candidates(signals, max_workers=body.max_workers)
        except Exception:  # pragma: no cover - defensive
            LOG.exception("candidates failed")
            raise HTTPException(
                status_code=500, detail="internal error during candidates") from None
        return _cached_response(request, matches, config=config)

    @v1.post("/identify/video", response_model=VideoIdentifyResponse)
    def identify_video_endpoint(request: Request, body: VideoIdentifyRequest,
                                refresh: bool = False) -> Response:
        """Identify a video from its file name (plus optional duration and
        hints). The name is parsed like a library scan would parse it; the
        server never opens a file."""
        name = _video_basename(body.filename)
        parsed = extract_signals(LocalMediaFile(path=Path(name), kind="video"), probe=False)
        fields = parsed.model_dump(exclude_none=True)
        if body.duration is not None and parsed.runtime is None:
            fields["runtime"] = body.duration
        unknown = sorted(set(body.hints) - set(Signals.model_fields))
        if unknown:
            raise HTTPException(status_code=422,
                                detail=f"unknown hint field(s): {', '.join(unknown)}")
        fields.update(body.hints)
        try:
            signals = Signals(**fields)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=_validation_message(e)) from None
        embedded = extract_embedded_ids(
            name, is_true_episodic=bool(_SXXEXX_RE.search(Path(name).stem)))
        result = _resolve(signals, body.max_workers, refresh)
        return _cached_response(
            request,
            VideoIdentifyResponse(filename=name, signals=signals,
                                  embedded_ids=embedded, result=result),
            config=config, degraded=bool(result.provider_errors))

    @shared.post("/identify/audio", response_model=AudioIdentifyResponse)
    async def identify_audio_endpoint(
        file: UploadFile = File(None),
        path: Optional[str] = None,
        refresh: bool = False,
    ) -> AudioIdentifyResponse:
        """Identify a track from an uploaded file, or from ``path`` when it
        names a file under one of the configured audio roots
        (``METADATARR_AUDIO_ROOTS``); any other path is refused with 403."""
        from metadatarr.identify import AudioIdentifyError, identify_audio_async

        if file is None and not path:
            raise HTTPException(
                status_code=422, detail="provide either a `file` upload or a `path`")

        if file is not None:
            source = await file.read(config.max_upload_bytes + 1)
            if len(source) > config.max_upload_bytes:
                raise HTTPException(status_code=413, detail="upload too large")
        else:
            try:
                source = resolve_allowed_path(path, config.audio_roots)
            except PathNotAllowed as e:
                raise HTTPException(status_code=403, detail=str(e)) from None

        try:
            with bypass_cache(refresh):
                match = await identify_audio_async(source)
        except AudioIdentifyError as e:
            raise HTTPException(status_code=503, detail=str(e)) from None
        except Exception:  # pragma: no cover - defensive
            LOG.exception("audio identify failed")
            raise HTTPException(
                status_code=500, detail="internal error during audio identify") from None

        return AudioIdentifyResponse(
            matched=match.matched,
            title=match.title,
            artist=match.artist,
            album=match.album,
            isrc=match.isrc,
            cover_art=match.cover_art,
            external_ids=match.external_ids,
        )

    @shared.post("/enrich", response_model=ExternalIds)
    def enrich_endpoint(request: Request, body: EnrichRequest,
                        refresh: bool = False) -> Response:
        from mediavocab import MediaType

        try:
            medium = MediaType(body.medium) if body.medium else None
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"invalid medium: {e}") from None
        try:
            with bypass_cache(refresh):
                ids = run_enrich(
                    body.external_ids,
                    medium=medium,
                    apply_maps=body.apply_maps,
                    max_workers=body.max_workers,
                )
        except Exception:  # pragma: no cover - defensive
            LOG.exception("enrich failed")
            raise HTTPException(
                status_code=500, detail="internal error during enrich") from None
        return _cached_response(request, ids, config=config)

    app.include_router(shared, prefix=API_PREFIX)
    app.include_router(v1, prefix=API_PREFIX)
    app.include_router(shared, include_in_schema=False)
