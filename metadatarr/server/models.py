# SPDX-License-Identifier: Apache-2.0
"""Request / response pydantic models for the HTTP server.

``metadatarr`` ships a single top-level ``metadatarr/models.py`` module (not a
package), so the server's request/response shapes live here instead of a
``metadatarr/models/api.py`` submodule.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals


class ResolveRequest(Signals):
    """A :class:`~mediavocab.models.signals.Signals` bag posted as JSON.

    Identical fields to ``Signals`` — subclassed only so FastAPI can document
    it as a dedicated request schema without callers needing to import
    ``mediavocab`` themselves.
    """

    model_config = ConfigDict(extra="forbid")

    max_workers: int = Field(default=8, ge=1, le=32)


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


class ProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    active: int
    providers: List[ProviderInfo]
