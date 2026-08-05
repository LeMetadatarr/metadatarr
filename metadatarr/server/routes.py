# SPDX-License-Identifier: Apache-2.0
"""JSON API routes for the metadatarr server.

Mounted onto a FastAPI ``app`` by :func:`register_routes`. Bodies / responses
use pydantic models from :mod:`metadatarr.server.models` plus the resolver's
own :class:`~metadatarr.resolve.base.ResolveResult` /
:class:`~metadatarr.resolve.base.ProviderMatch`.
"""
from __future__ import annotations

import logging
from typing import List, Optional

# Safe at module level: this module is only ever imported by
# metadatarr.server.app.create_app(), which calls _require_fastapi() first.
# Needed as a real (non-forward-ref) name so FastAPI/pydantic can resolve the
# `UploadFile` parameter annotation on identify_audio_endpoint below — a
# purely-local `from fastapi import ...` inside register_routes() leaves the
# name unresolvable under `from __future__ import annotations`.
from fastapi import File, UploadFile

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
from metadatarr.server.models import (
    AudioIdentifyResponse,
    EnrichRequest,
    HealthResponse,
    ProviderInfo,
    ProvidersResponse,
    ResolveRequest,
)
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


def register_routes(app, templates) -> None:
    from fastapi import HTTPException

    @app.get("/healthz", response_model=HealthResponse)
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

    @app.get("/providers", response_model=ProvidersResponse)
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
        )

    @app.post("/resolve", response_model=ResolveResult)
    def resolve_endpoint(request: ResolveRequest) -> ResolveResult:
        payload = request.model_dump(exclude={"max_workers"})
        signals = Signals(**payload)
        try:
            return run_resolve(signals, max_workers=request.max_workers)
        except Exception:  # pragma: no cover - defensive
            LOG.exception("resolve failed")
            raise HTTPException(
                status_code=500, detail="internal error during resolve") from None

    @app.post("/candidates", response_model=List[ProviderMatch])
    def candidates_endpoint(request: ResolveRequest) -> List[ProviderMatch]:
        payload = request.model_dump(exclude={"max_workers"})
        signals = Signals(**payload)
        try:
            return run_candidates(signals, max_workers=request.max_workers)
        except Exception:  # pragma: no cover - defensive
            LOG.exception("candidates failed")
            raise HTTPException(
                status_code=500, detail="internal error during candidates") from None

    @app.post("/identify/audio", response_model=AudioIdentifyResponse)
    async def identify_audio_endpoint(
        file: UploadFile = File(None),
        path: Optional[str] = None,
    ) -> AudioIdentifyResponse:
        from metadatarr.identify import AudioIdentifyError, identify_audio_async

        if file is None and not path:
            raise HTTPException(
                status_code=422, detail="provide either a `file` upload or a `path`")

        if file is not None:
            audio_bytes = await file.read()
            source = audio_bytes
        else:
            source = path

        try:
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

    @app.post("/enrich", response_model=ExternalIds)
    def enrich_endpoint(request: EnrichRequest) -> ExternalIds:
        from mediavocab import MediaType

        try:
            medium = MediaType(request.medium) if request.medium else None
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"invalid medium: {e}") from None
        try:
            return run_enrich(
                request.external_ids,
                medium=medium,
                apply_maps=request.apply_maps,
                max_workers=request.max_workers,
            )
        except Exception:  # pragma: no cover - defensive
            LOG.exception("enrich failed")
            raise HTTPException(
                status_code=500, detail="internal error during enrich") from None
