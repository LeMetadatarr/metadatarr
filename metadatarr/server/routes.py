# SPDX-License-Identifier: Apache-2.0
"""JSON API routes for the metadatarr server.

Mounted onto a FastAPI ``app`` by :func:`register_routes`. Bodies / responses
use pydantic models from :mod:`metadatarr.server.models` plus the resolver's
own :class:`~metadatarr.resolve.base.ResolveResult` /
:class:`~metadatarr.resolve.base.ProviderMatch`.

Every route lives under ``/api/v1``. The routes that predate versioning are
also served at their unversioned paths (``/resolve``, ``/healthz``, ...),
hidden from the OpenAPI schema. ``POST /resolve`` keeps its original request
model there; under ``/api/v1`` it also takes external ids.

The catalogue routes (``/api/v1/lookup``, ``/api/v1/credits``,
``/api/v1/person``, ``/api/v1/extras``, ``/api/v1/variants``) answer by
identifier through :mod:`metadatarr.catalog`.
A question no available provider can answer is ``501``, an identifier no
catalogue knows is ``404``, and every asked provider failing is ``502``.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Safe at module level: this module is only ever imported by
# metadatarr.server.app.create_app(), which calls _require_fastapi() first.
# Needed as a real (non-forward-ref) name so FastAPI/pydantic can resolve the
# `UploadFile` parameter annotation on identify_audio_endpoint below — a
# purely-local `from fastapi import ...` inside register_routes() leaves the
# name unresolvable under `from __future__ import annotations`.
from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

# Triggers built-in provider self-registration as a side effect of import.
import metadatarr.resolve.providers  # noqa: F401

from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals

from metadatarr.resolve.base import (
    KindedProviderMatch,
    ProviderMatch,
    ResolveResult,
    SearchCandidate,
    all_providers,
    candidates as run_candidates,
    kind_candidates,
    enrich as run_enrich,
    resolve as run_resolve,
)
from metadatarr import catalog
from metadatarr.offline import layer as offline
from metadatarr.client import check_dvdcompare_url, check_fetched_urls
from metadatarr.catalog import resolve as id_resolve
from metadatarr.catalog.resolve import _KIND_MEDIUM as KIND_MEDIUM
from metadatarr.resolve._errors import ProviderError
from metadatarr.library import LocalMediaFile, _SXXEXX_RE, extract_embedded_ids, extract_signals
from metadatarr.server.config import ServerConfig
from metadatarr.server.models import (
    AudioIdentifyResponse,
    BatchItemResult,
    BatchResolveRequest,
    BatchResolveResponse,
    CandidatesRequest,
    EnrichRequest,
    HealthResponse,
    IdResolveRequest,
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


def _finite(value: Any) -> Any:
    """Replace non-finite floats (not valid JSON) with ``None``."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


def _cached_response(request: Request, payload: Any, *, config: ServerConfig,
                     degraded: bool = False, max_age: Optional[int] = None) -> Response:
    """JSON response carrying an ``ETag`` and a ``Cache-Control`` lifetime
    equal to the provider cache TTL (or ``max_age`` when given).

    A result produced while a provider failed (``degraded``) is sent with
    ``no-cache`` so clients revalidate it. A ``GET`` whose
    ``If-None-Match`` names the current ETag gets ``304 Not Modified``.
    """
    body = json.dumps(_finite(jsonable_encoder(payload)), separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    etag = _etag(body)
    scope = "private" if config.auth_enabled else "public"
    age = _max_age() if max_age is None else max_age
    cache_control = "no-cache" if degraded or age <= 0 else f"{scope}, max-age={age}"
    headers = {"ETag": etag, "Cache-Control": cache_control}
    inm = request.headers.get("if-none-match")
    if request.method == "GET" and inm and _etag_matches(inm, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


def _charge_batch(request: Request, items: int) -> None:
    """Bill a batch ``items`` rate-limit tokens (the access-control middleware
    already took one). A batch the bucket cannot cover is refused with
    ``429`` and ``Retry-After``; the middleware's token stays spent, so refused
    batches are not free. A batch larger than the whole burst can never be
    covered and says so."""
    bucket = getattr(request.app.state, "rate_bucket", None)
    ident = getattr(request.state, "rate_ident", None)
    if bucket is None or ident is None or items <= 1:
        return
    if items > bucket.burst:
        raise HTTPException(
            status_code=429,
            detail=(f"batch of {items} items is larger than the rate-limit burst of "
                    f"{bucket.burst}; send at most {bucket.burst} items per batch"))
    bucket.refund(ident, 1)
    wait = bucket.take(ident, items)
    if wait > 0:
        bucket.take(ident, 1)
        # The retry pays the middleware's token first, then the batch.
        retry = wait + 1.0 / bucket.rate
        raise HTTPException(
            status_code=429, detail="rate limit exceeded",
            headers={"Retry-After": str(max(1, math.ceil(retry)))})


def _error(status: int, error: str, **fields: Any) -> JSONResponse:
    """A JSON error answer that clients and intermediaries must not cache."""
    return JSONResponse(_finite(jsonable_encoder({"error": error, **fields})), status_code=status,
                        headers={"Cache-Control": "no-store"})


def _catalog_max_age() -> int:
    store = catalog.base.cache()
    return int(store.ttl) if store.max_entries > 0 else 0


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

    # ``shared`` holds the routes that also answer at their unversioned path;
    # ``legacy`` the unversioned routes whose versioned form differs.
    shared = APIRouter()
    legacy = APIRouter()
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
                capabilities={**catalog.capabilities_of(name),
                              "search_kinds": sorted(p.search_kinds or ())},
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

    @legacy.post("/resolve", response_model=ResolveResult)
    def resolve_endpoint(request: Request, body: ResolveRequest,
                         refresh: bool = False) -> Response:
        payload = body.model_dump(exclude={"max_workers"})
        result = _resolve(Signals(**payload), body.max_workers, refresh)
        return _cached_response(request, result, config=config,
                                degraded=bool(result.provider_errors))

    @v1.post("/resolve")
    def resolve_ids_endpoint(request: Request, body: IdResolveRequest,
                             refresh: bool = False) -> Response:
        """Resolve a title, a title narrowed by external ids, or ids alone.

        The answer is the ``ResolveResult`` of the unversioned route plus
        ``match`` (``item``, ``confidence``, ``source``, ``credits``,
        ``id_conflicts``, in the catalogue shapes), ``providers`` (those that
        contributed) and ``errors`` (those that failed). Ids that no provider
        can look up, with no title, are ``501``; ids no catalogue knows, with
        no title, are ``404``."""
        ids = {k.strip().lower(): v.strip() for k, v in body.ids.items() if k.strip() and v and v.strip()}
        if not ids and not body.title:
            return _error(422, "invalid request", message="give a title or at least one id")
        signals = Signals(**body.model_dump(exclude={"max_workers", "ids", "kind"}))
        _count()
        try:
            with bypass_cache(refresh):
                out = id_resolve.resolve(signals, ids, (body.kind or "").strip().lower() or None,
                                         max_workers=body.max_workers, refresh=refresh)
        except catalog.InvalidId as e:
            return _error(422, "invalid id", message=str(e))
        except ValueError as e:
            return _error(422, "invalid request", message=str(e))
        if not out.found and not body.title:
            if out.unsupported and not out.errors and len(out.unsupported) == len(ids):
                return _error(501, "not supported", provider=None,
                              message=f"no available provider looks up {', '.join(out.unsupported)} ids")
            if out.errors and not out.providers:
                return _error(502, "upstream failed", errors=out.errors, unsupported=out.unsupported)
            return _error(404, "not found", errors=out.errors, unsupported=out.unsupported)
        payload = {**jsonable_encoder(out.result), "match": out.match, "providers": out.providers,
                   "errors": out.errors, "unsupported": out.unsupported}
        if out.origin is not None:
            payload["origin"] = out.origin
        return _cached_response(request, payload, config=config,
                                degraded=bool(out.errors or out.result.provider_errors))

    def _catalog(request: Request, method: str, scheme: str, value: str, kind: Optional[str],
                 provider: Optional[str], refresh: bool, title: Optional[str] = None,
                 year: Optional[int] = None) -> Response:
        if len((title or "").strip()) > catalog.base.MAX_VALUE_LENGTH:
            return _error(422, "invalid request",
                          message=f"title is longer than {catalog.base.MAX_VALUE_LENGTH} characters")
        try:
            if method == "variants" and not (title or "").strip():
                found = _title_of(scheme, value, kind, provider or None, refresh)
                if isinstance(found, Response):
                    return found
                title, found_year = found
                year = year or found_year
            answer = catalog.ask(method, scheme, value, kind, provider=provider or None, refresh=refresh,
                                 title=title, year=year)
        except catalog.NotSupported as e:
            return _error(501, "not supported", provider=e.provider, message=str(e))
        except catalog.InvalidId as e:
            return _error(422, "invalid id", message=str(e))
        except ValueError as e:
            return _error(422, "invalid request", message=str(e))
        if answer.value is None:
            if answer.errors and len(answer.errors) == len(answer.asked):
                return _error(502, "upstream failed", providers=answer.asked, errors=answer.errors)
            return _error(404, "not found", providers=answer.asked, errors=answer.errors)
        value = answer.value
        if method == "lookup":
            body: Dict[str, Any] = {"item": value}
        elif method == "credits":
            body = {"credits": value}
        elif method == "extras":
            body = {"provider": answer.providers[0], "extras": value}
        elif method == "variants":
            body = {"variants": value}
        else:
            body = {"person": value.person, "credits": value.credits}
        body.update(providers=answer.providers, errors=answer.errors, truncated=answer.truncated)
        if answer.origin is not None:
            body["origin"] = answer.origin
        return _cached_response(request, body, config=config, degraded=bool(answer.errors),
                                max_age=_catalog_max_age())

    def _title_of(scheme: str, value: str, kind: Optional[str], provider: Optional[str], refresh: bool):
        """``(title, year)`` of the work a variants question names by id alone,
        or the error answer: 501 when no provider can answer variants or look
        the id up, 404 when no catalogue knows it, 502 when every one failed."""
        scheme, value, kind = catalog.base.check_request("variants", scheme, value, kind)
        catalog.base.capable_sources("variants", scheme, kind, provider)
        try:
            found = catalog.ask("lookup", scheme, value, kind, refresh=refresh, children=False)
        except catalog.NotSupported as e:
            return _error(501, "not supported", provider=None, message=f"title is required: {e}")
        if found.value is None:
            if found.errors and len(found.errors) == len(found.asked):
                return _error(502, "upstream failed", providers=found.asked, errors=found.errors)
            return _error(404, "not found", providers=found.asked, errors=found.errors)
        return found.value.title, found.value.year

    @v1.get("/lookup")
    def lookup_endpoint(request: Request, scheme: str, value: str, kind: Optional[str] = None,
                        provider: Optional[str] = None, refresh: bool = False) -> Response:
        """An item's details with its children one level down (series to
        seasons, season to episodes, show to episodes, artist to albums,
        album to tracks, author to books, audiobook to chapters, collection
        to movies)."""
        return _catalog(request, "lookup", scheme, value, kind, provider, refresh)

    @v1.get("/credits")
    def credits_endpoint(request: Request, scheme: str, value: str, kind: Optional[str] = None,
                         provider: Optional[str] = None, refresh: bool = False) -> Response:
        """The people, groups and companies credited on an item, each with a
        role from the published vocabulary."""
        return _catalog(request, "credits", scheme, value, kind, provider, refresh)

    @v1.get("/person")
    def person_endpoint(request: Request, scheme: str, value: str, provider: Optional[str] = None,
                        refresh: bool = False) -> Response:
        """A person and their filmography: credits whose ``item`` is set."""
        return _catalog(request, "person", scheme, value, None, provider, refresh)

    @v1.get("/extras")
    def extras_endpoint(request: Request, scheme: str, value: str, kind: Optional[str] = None,
                        provider: Optional[str] = None, refresh: bool = False) -> Response:
        """The videos that belong to an item (trailers, teasers, featurettes,
        behind the scenes, music videos), each with its type, site, key,
        address, language, resolution and date; ``provider`` names the
        catalogue that listed them."""
        return _catalog(request, "extras", scheme, value, kind, provider, refresh)

    @v1.get("/variants")
    def variants_endpoint(request: Request, scheme: str, value: str, kind: Optional[str] = None,
                          title: Optional[str] = None, year: Optional[int] = None,
                          provider: Optional[str] = None, refresh: bool = False) -> Response:
        """The fan edits of a work, each an item with ``extra.variant`` and,
        when the catalogue gives one, ``ext_ids.ifdb``. The work is searched
        by ``title``; without one, its title is looked up by its id."""
        return _catalog(request, "variants", scheme, value, kind, provider, refresh, title, year)

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

        _charge_batch(request, len(body.items))

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

    @shared.post("/candidates", response_model=List[Union[ProviderMatch, KindedProviderMatch, SearchCandidate]])
    def candidates_endpoint(request: Request, body: CandidatesRequest,
                            refresh: bool = False) -> Response:
        """Every provider's candidates, ranked, without consolidation.

        Without ``kind`` the rows are the providers' matches. With a media
        ``kind`` (``movie``, ``series``, ...) they are the same matches, the
        medium defaulting to the kind's, each also carrying the
        search-candidate fields (``kind``, ``title``, ``year``, ``ids``,
        ``poster``, ``overview``, ``aliases``, ``medium``). With any other
        ``kind`` (``performer``, ``studio``, ``scene``, ...) only providers
        whose ``search_kinds`` list it answer, and each row is a search
        candidate; no such provider is an empty list."""
        kind = (body.kind or "").strip().lower() or None
        payload = body.model_dump(exclude={"max_workers", "kind"})
        if kind and kind not in KIND_MEDIUM:
            if not (payload.get("title") or "").strip():
                return _cached_response(request, [], config=config)
            errors: List[ProviderError] = []
            try:
                with bypass_cache(refresh):
                    rows = kind_candidates(kind, Signals(**payload), max_workers=body.max_workers, sink=errors)
            except Exception:  # pragma: no cover - defensive
                LOG.exception("candidates failed")
                raise HTTPException(
                    status_code=500, detail="internal error during candidates") from None
            response = _cached_response(request, rows, config=config, degraded=bool(errors))
            if errors and not rows:
                response.headers["Cache-Control"] = "no-store"
            return response
        if kind and not payload.get("medium"):
            payload["medium"] = KIND_MEDIUM[kind]
        signals = Signals(**payload)
        try:
            with bypass_cache(refresh):
                matches = run_candidates(signals, max_workers=body.max_workers)
        except Exception:  # pragma: no cover - defensive
            LOG.exception("candidates failed")
            raise HTTPException(
                status_code=500, detail="internal error during candidates") from None
        if kind:
            return _cached_response(request, [
                {**jsonable_encoder(m), **jsonable_encoder(SearchCandidate.from_match(m, kind))}
                for m in matches], config=config)
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
        extra = body.external_ids.extra or {}
        try:
            if extra.get("dvdcompare_url") not in (None, ""):
                check_dvdcompare_url(extra["dvdcompare_url"])
            check_fetched_urls(extra)
        except ValueError as e:
            return _error(422, "invalid id", message=str(e))
        try:
            catalog.base.check_external_ids(body.external_ids)
        except catalog.InvalidId as e:
            return _error(422, "invalid id", message=str(e))
        try:
            with bypass_cache(refresh), offline.collect_origins() as served:
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
        response = _cached_response(request, ids, config=config)
        if offline.enabled():
            response.headers["X-Metadatarr-Origin"] = (
                ", ".join(f"offline {o['dataset']}@{o['revision']}" for o in served) or "live")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Rejected inputs are echoed back; NaN/Infinity among them are not JSON.
        return JSONResponse({"detail": _finite(jsonable_encoder(exc.errors()))}, status_code=422)

    app.include_router(shared, prefix=API_PREFIX)
    app.include_router(v1, prefix=API_PREFIX)
    app.include_router(shared, include_in_schema=False)
    app.include_router(legacy, include_in_schema=False)
