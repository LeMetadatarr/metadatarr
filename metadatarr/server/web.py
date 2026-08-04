# SPDX-License-Identifier: Apache-2.0
"""Build-free WebUI (server-rendered Jinja2 + htmx) for metadatarr."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import Form, Request

# Triggers built-in provider self-registration as a side effect of import.
import metadatarr.resolve.providers  # noqa: F401

from mediavocab import MediaType

from metadatarr.resolve.base import candidates as run_candidates, consolidate
from metadatarr.server.models import ProviderInfo, ProvidersResponse
from metadatarr.version import __version__


def _ids_items(external_ids) -> List[Tuple[str, Any]]:
    """Non-empty (field, value) pairs from an ExternalIds instance."""
    out: List[Tuple[str, Any]] = []
    if external_ids is None:
        return out
    for name in type(external_ids).model_fields:
        if name == "extra":
            continue
        val = getattr(external_ids, name, None)
        if val is not None:
            out.append((name, val))
    for k, v in (external_ids.extra or {}).items():
        if v is not None:
            out.append((f"extra.{k}", v))
    return out


def _signal_items(signals) -> List[Tuple[str, Any]]:
    """A short, human-relevant subset of a Signals bag's populated fields."""
    if signals is None:
        return []
    keys = ("title", "artist", "year", "medium", "country", "runtime",
            "season", "episode", "edition", "region")
    out: List[Tuple[str, Any]] = []
    for k in keys:
        v = getattr(signals, k, None)
        if v is not None:
            out.append((k, getattr(v, "value", v)))
    return out


def _providers_response() -> ProvidersResponse:
    from metadatarr.resolve.base import all_providers

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


def register_web(app, templates) -> None:
    def _ctx(**extra) -> Dict[str, Any]:
        ctx = {"version": __version__}
        ctx.update(extra)
        return ctx

    @app.get("/")
    def resolver_playground(request: Request):
        media_types = [m.value for m in MediaType if m not in
                       {MediaType.GENERIC, MediaType.NOT_MEDIA, MediaType.CONTROL}]
        return templates.TemplateResponse(
            request,
            "resolve.html",
            _ctx(active="resolve", media_types=media_types),
        )

    @app.post("/ui/resolve")
    def ui_resolve(
        request: Request,
        title: Optional[str] = Form(default=None),
        artist: Optional[str] = Form(default=None),
        year: Optional[int] = Form(default=None),
        medium: Optional[str] = Form(default=None),
        season: Optional[int] = Form(default=None),
        episode: Optional[int] = Form(default=None),
        country: Optional[str] = Form(default=None),
        edition: Optional[str] = Form(default=None),
    ):
        return _resolve_fragment(
            templates, request, title=title, artist=artist, year=year,
            medium=medium, season=season, episode=episode, country=country,
            edition=edition,
        )

    @app.get("/ui/providers")
    def ui_providers(request: Request):
        return templates.TemplateResponse(
            request,
            "providers.html",
            _ctx(active="providers", providers_resp=_providers_response()),
        )

    @app.get("/ui/mappings")
    def ui_mappings(request: Request):
        from metadatarr.resolve.mappings import (
            _package_mappings_path,
            _user_mappings_path,
            get_store,
        )

        store = get_store()
        by_role: Dict[str, List[Tuple[str, str]]] = {}
        for entry in store._entries:  # noqa: SLF001 — read-only inspection
            role_name = entry.role.value
            bucket = by_role.setdefault(role_name, [])
            label = entry.name or "(unnamed)"
            for k, v in entry.identifiers.items():
                bucket.append((f"{label} :: {k}", v))

        shipped = _package_mappings_path()
        overlay = _user_mappings_path()
        return templates.TemplateResponse(
            request,
            "mappings.html",
            _ctx(
                active="mappings", mappings=by_role,
                shipped_path=str(shipped) if shipped else "(unavailable)",
                overlay_path=str(overlay),
                overlay_exists=overlay.exists(),
            ),
        )


def _resolve_fragment(templates, request, *, title, artist, year, medium,
                      season, episode, country, edition):
    from mediavocab.models.signals import Signals

    kwargs: Dict[str, Any] = {}
    if title:
        kwargs["title"] = title
    if artist:
        kwargs["artist"] = artist
    if year:
        kwargs["year"] = year
    if medium:
        try:
            kwargs["medium"] = MediaType(medium)
        except ValueError:
            return templates.TemplateResponse(
                request,
                "fragments/resolve_result.html",
                {
                    "candidates": [],
                    "result": None,
                    "error": f"invalid medium: {medium!r}",
                    "ids_items": _ids_items,
                    "signal_items": _signal_items,
                },
            )
    if season:
        kwargs["season"] = season
    if episode:
        kwargs["episode"] = episode
    if country:
        kwargs["country"] = country
    if edition:
        kwargs["edition"] = edition

    signals = Signals(**kwargs)
    matches = run_candidates(signals)
    result = consolidate(matches, signals)

    return templates.TemplateResponse(
        request,
        "fragments/resolve_result.html",
        {
            "candidates": matches,
            "result": result,
            "ids_items": _ids_items,
            "signal_items": _signal_items,
        },
    )
