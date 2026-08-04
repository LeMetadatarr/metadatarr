# SPDX-License-Identifier: Apache-2.0
"""JSON API routes for the metadatarr server.

Mounted onto a FastAPI ``app`` by :func:`register_routes`. Bodies / responses
use pydantic models from :mod:`metadatarr.server.models` plus the resolver's
own :class:`~metadatarr.resolve.base.ResolveResult` /
:class:`~metadatarr.resolve.base.ProviderMatch`.
"""
from __future__ import annotations

from typing import List

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
    EnrichRequest,
    HealthResponse,
    ProviderInfo,
    ProvidersResponse,
    ResolveRequest,
)
from metadatarr.version import __version__


def register_routes(app, templates) -> None:
    from fastapi import HTTPException

    @app.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        return HealthResponse(version=__version__)

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
        except Exception as e:  # pragma: no cover - defensive
            raise HTTPException(status_code=500, detail=str(e)) from None

    @app.post("/candidates", response_model=List[ProviderMatch])
    def candidates_endpoint(request: ResolveRequest) -> List[ProviderMatch]:
        payload = request.model_dump(exclude={"max_workers"})
        signals = Signals(**payload)
        try:
            return run_candidates(signals, max_workers=request.max_workers)
        except Exception as e:  # pragma: no cover - defensive
            raise HTTPException(status_code=500, detail=str(e)) from None

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
        except Exception as e:  # pragma: no cover - defensive
            raise HTTPException(status_code=500, detail=str(e)) from None
