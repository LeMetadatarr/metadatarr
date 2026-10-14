# SPDX-License-Identifier: Apache-2.0
"""Resolve with external identifiers: a title narrowed by ids, or ids alone.

The answer is the resolver's :class:`~metadatarr.resolve.base.ResolveResult`
plus a ``match`` in the catalogue shapes (item, confidence, source, credits),
the providers that contributed and the providers that failed.

- When a catalogue can look one of the ids up, that item is the answer. Its
  confidence is 1.0 for ids alone; with a title, it is how well the title and
  year agree with the catalogue's (``match_quality``), halved when another of
  the given ids contradicts the catalogue's.
- Otherwise, with a title, the title resolve runs and every candidate that
  carries one of the given ids with a different value is dropped; a candidate
  that carries one with the same value is raised to at least 0.95.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from mediavocab import MediaType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals, match_quality

from metadatarr.catalog import base as catalog
from metadatarr.catalog.ids import from_native, person_ids, to_native
from metadatarr.catalog.roles import COMPANY_ROLES, normalise_role
from metadatarr.catalog.shapes import Credit, Item, Person, merge_credits
from metadatarr.resolve._errors import ProviderError
from metadatarr.resolve.base import (
    ProviderMatch,
    ResolutionConflict,
    ResolveResult,
    add_variants,
    candidates as run_candidates,
    consolidate,
    resolve as run_resolve,
)

AGREEMENT_FLOOR = 0.95

_MEDIUM_KIND = {"movie": "movie", "short_film": "movie", "episodic_series": "series", "tv": "series",
                "music": "album", "music_video": "track", "podcast": "show", "audio_drama": "show",
                "audiobook": "audiobook", "book": "book", "comic": "book"}
_KIND_MEDIUM = {"movie": "movie", "collection": "movie", "series": "episodic_series", "season": "episodic_series",
                "episode": "episodic_series", "artist": "music", "album": "music", "track": "music",
                "author": "book", "book": "book", "show": "podcast", "audiobook": "audiobook",
                "chapter": "audiobook"}
_ENTITY_KIND = {"person": "person", "group": "group", "organisation": "company"}


@dataclass
class IdResolve:
    result: ResolveResult
    match: Optional[Dict[str, Any]]
    providers: List[str] = field(default_factory=list)
    errors: List[ProviderError] = field(default_factory=list)
    unsupported: List[str] = field(default_factory=list)
    found: bool = False


def kind_for(signals: Signals, kind: Optional[str]) -> Optional[str]:
    if kind:
        return kind
    medium = getattr(signals.medium, "value", signals.medium)
    return _MEDIUM_KIND.get(medium or "")


def _credits(relations) -> List[Credit]:
    out: List[Credit] = []
    for role, entities in (relations or {}).items():
        word = getattr(role, "value", role)
        std = normalise_role(word.replace("featuring", "featured artist").replace("channel", "network"))
        if not std or std == "other":
            continue
        for e in entities or []:
            if not (e.name or "").strip():
                continue
            kind = _ENTITY_KIND.get(getattr(e.kind, "value", e.kind) or "",
                                    "company" if std in COMPANY_ROLES else "person")
            out.append(Credit(person=Person(name=e.name.strip(), kind=kind, ext_ids=person_ids(e.external_ids),
                                            image_url=e.image_url or ""), role=std))
    return merge_credits(out)


def _contradicts(candidate: ExternalIds, given: ExternalIds) -> bool:
    for name in type(given).model_fields:
        if name == "extra":
            continue
        want = getattr(given, name)
        have = getattr(candidate, name, None)
        if want is not None and have is not None and str(want) != str(have):
            return True
    return False


def _agrees(candidate: ExternalIds, given: ExternalIds) -> bool:
    for name in type(given).model_fields:
        if name == "extra":
            continue
        want = getattr(given, name)
        if want is not None and str(getattr(candidate, name, None)) == str(want):
            return True
    return False


def _by_ids(ids: Dict[str, str], kind: Optional[str], refresh: bool, out: IdResolve) -> Optional[Item]:
    for scheme, value in ids.items():
        if (kind or catalog.default_kind(scheme, value)) is None:
            out.unsupported.append(scheme)
            continue
        try:
            answer = catalog.ask("lookup", scheme, value, kind, refresh=refresh, children=False)
        except catalog.NotSupported:
            out.unsupported.append(scheme)
            continue
        out.errors.extend(answer.errors)
        if answer.value is not None:
            out.providers.extend(answer.providers)
            return answer.value.model_copy(deep=True)
    return None


def resolve(signals: Signals, ids: Dict[str, str], kind: Optional[str] = None, *,
            max_workers: int = 8, refresh: bool = False) -> IdResolve:
    """Resolve ``signals`` (a title, maybe empty) narrowed by ``ids`` ({scheme: value}).

    Raises :class:`ValueError` for a malformed id or kind."""
    kind = kind_for(signals, kind)
    if kind is not None and kind not in catalog.KINDS:
        raise ValueError(f"unknown kind {kind!r}; one of {', '.join(catalog.KINDS)}")
    out = IdResolve(result=ResolveResult(signals=signals), match=None)
    item = _by_ids(ids, kind, refresh, out) if ids else None
    if item is not None:
        out.found = True
        item.children = []
        confidence = 1.0
        if signals.title:
            local = Signals(title=signals.title, year=signals.year)
            confidence = max(match_quality(local, Signals(title=t, year=item.year))
                             for t in {item.title, item.original_title} if t)
        # An id the catalogue holds under another scheme (an Open Library
        # edition beside its work) agrees with the item.
        known = set(item.ext_ids.values())
        clashes = sorted(s for s, v in ids.items() if s in item.ext_ids and item.ext_ids[s] != v and v not in known)
        if clashes:
            confidence *= 0.5
            out.result.conflicts.append(ResolutionConflict(provider=out.providers[0], against="local"))
        medium = signals.medium or _KIND_MEDIUM.get(item.kind)
        found = Signals(title=item.title, year=item.year, medium=MediaType(getattr(medium, "value", medium))
                        if medium else None)
        native = to_native({**{s: v for s, v in ids.items() if v not in known}, **item.ext_ids}, item.kind)
        out.result = ResolveResult(
            signals=found, external_ids=native, conflicts=out.result.conflicts,
            accepted=[ProviderMatch(provider=out.providers[0], confidence=round(confidence, 4), signals=found,
                                    external_ids=native)])
        out.match = {"item": item, "confidence": round(confidence, 4), "source": out.providers[0], "credits": [],
                     "id_conflicts": clashes}
        return out
    if not signals.title:
        return out
    if ids:
        given = to_native(ids, kind)
        sink: List[ProviderError] = []
        kept: List[ProviderMatch] = []
        dropped: List[ProviderMatch] = []
        for m in run_candidates(signals, max_workers=max_workers, sink=sink):
            if _contradicts(m.external_ids, given):
                dropped.append(m)
            elif _agrees(m.external_ids, given):
                kept.append(m.model_copy(update={"confidence": max(m.confidence, AGREEMENT_FLOOR)}))
            else:
                kept.append(m)
        result = consolidate(kept, signals)
        result.provider_errors = sink
        result.dropped = dropped + result.dropped
        result.conflicts = ([ResolutionConflict(provider=m.provider, against="local") for m in dropped]
                            + result.conflicts)
        if signals.include_variants:
            add_variants(result, signals, max_workers=max_workers)
    else:
        result = run_resolve(signals, max_workers=max_workers)
    out.result = result
    out.errors.extend(result.provider_errors)
    out.providers = list(dict.fromkeys(m.provider for m in result.accepted))
    if result.accepted and result.signals is not None:
        out.found = True
        s = result.signals
        item = Item(kind=kind or "", title=s.title or "", year=s.year,
                    runtime_min=round(s.runtime / 60, 2) if s.runtime else None,
                    ext_ids={**from_native(result.external_ids, kind), **ids})
        confidence = max(m.confidence for m in result.accepted)
        out.match = {"item": item, "confidence": round(confidence, 4), "source": out.providers[0],
                     "credits": _credits(result.relations), "id_conflicts": []}
    return out
