# SPDX-License-Identifier: Apache-2.0
"""Request / response pydantic models for the HTTP server.

``metadatarr`` ships a single top-level ``metadatarr/models.py`` module (not a
package), so the server's request/response shapes live here instead of a
``metadatarr/models/api.py`` submodule.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals

from metadatarr.resolve.base import ResolveResult


class ResolveRequest(Signals):
    """A :class:`~mediavocab.models.signals.Signals` bag posted as JSON.

    Identical fields to ``Signals`` — subclassed only so FastAPI can document
    it as a dedicated request schema without callers needing to import
    ``mediavocab`` themselves.
    """

    model_config = ConfigDict(extra="forbid")

    max_workers: int = Field(default=8, ge=1, le=32)


MAX_BATCH_ITEMS = 100


class BatchResolveRequest(BaseModel):
    """Up to :data:`MAX_BATCH_ITEMS` signal bags, each resolved on its own.

    Items are validated one by one, so a malformed item becomes an error in
    its own slot of the response instead of failing the whole batch.
    """

    model_config = ConfigDict(extra="forbid")

    items: List[Dict[str, Any]] = Field(min_length=1, max_length=MAX_BATCH_ITEMS)
    max_workers: int = Field(default=8, ge=1, le=32)


class BatchItemResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    ok: bool
    result: Optional[ResolveResult] = None
    error: Optional[str] = None


class BatchResolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: List[BatchItemResult]


class VideoIdentifyRequest(BaseModel):
    """A video file described by its name, as a client sees it.

    Only the final path component of ``filename`` is used; the server never
    opens it. ``duration`` (seconds) fills ``Signals.runtime`` when the name
    does not carry one. ``size`` (bytes) is accepted for clients that send it
    and is not used for matching. ``hints`` are ``Signals`` fields that
    override what the name parser found.
    """

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=1024)
    duration: Optional[float] = Field(default=None, gt=0)
    size: Optional[int] = Field(default=None, ge=0)
    hints: Dict[str, Any] = Field(default_factory=dict)
    max_workers: int = Field(default=8, ge=1, le=32)


class VideoIdentifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    signals: Signals
    embedded_ids: Optional[ExternalIds] = None
    result: ResolveResult


class EnrichRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_ids: ExternalIds = Field(default_factory=ExternalIds)
    medium: Optional[str] = None
    apply_maps: bool = True
    max_workers: int = Field(default=8, ge=1, le=32)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    version: str
    providers_available: int = 0
    providers_total: int = 0


class StatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolves_total: int = 0
    cache_enabled: bool = False
    cache_entries: int = 0
    cache_bytes: int = 0


class ProviderInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    available: bool
    media: List[str] = Field(default_factory=list)
    modality: List[str] = Field(default_factory=list)
    genre_filter: List[str] = Field(default_factory=list)


class AudioIdentifyResponse(BaseModel):
    """Response for ``POST /identify/audio`` — Shazam hit + cross-catalog ids."""

    model_config = ConfigDict(extra="forbid")

    matched: bool
    title: str = ""
    artist: str = ""
    album: str = ""
    isrc: Optional[str] = None
    cover_art: str = ""
    external_ids: ExternalIds = Field(default_factory=ExternalIds)


class PluginInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    distribution: Optional[str] = None
    version: Optional[str] = None
    error: Optional[str] = None


class ProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    active: int
    providers: List[ProviderInfo]
    plugins: List[PluginInfo] = Field(default_factory=list)


def plugin_infos() -> List[PluginInfo]:
    """Status of the provider plugins loaded from installed distributions."""
    from metadatarr.resolve.providers import loaded_plugins

    return [
        PluginInfo(name=p.name, distribution=p.distribution, version=p.version, error=p.error)
        for p in loaded_plugins()
    ]
