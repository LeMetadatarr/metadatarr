"""Provider abstraction + tiny registry.

A provider is anything that, given a :class:`Signals` bag, returns a
:class:`ProviderMatch` with whatever cross-references it could resolve. The
registry is process-global; built-in providers self-register on import.

Typical usage::

    import metadatarr.resolve.providers          # triggers self-registration
    from metadatarr.resolve.base import resolve
    from mediavocab.models.signals import Signals
from mediavocab import MediaType

    result = resolve(Signals(title="Inception", medium=MediaType.MOVIE))
    print(result.external_ids.tmdb_movie)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field

from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from metadatarr.resolve.mappings import apply_mappings
from mediavocab import MediaType
from mediavocab.models.signals import Signals, SignalConflict, compare_signals as compare, merge_signals as merged


class ProviderMatch(BaseModel):
    """One provider's response: what they say the work is."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    confidence: float = Field(ge=0.0, le=1.0)
    signals: Signals = Field(default_factory=Signals)
    external_ids: ExternalIds = Field(default_factory=ExternalIds)
    relations: Dict[EntityRole, List[ProviderEntity]] = Field(default_factory=dict)


class ResolutionConflict(BaseModel):
    """One match disagreed with the running consolidation on these fields."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    """Name of the provider whose match was dropped."""
    against: str
    """``"local"`` if the disagreement was with the input signals, otherwise
    the name of the previously-accepted provider that anchored the result."""
    fields: List[SignalConflict] = Field(default_factory=list)
    """The specific :class:`SignalConflict` entries returned by
    :func:`signals.compare`."""


class ResolveResult(BaseModel):
    """Structured output from :func:`consolidate` and :func:`resolve`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    signals: Optional[Signals]
    """Signals merged from all accepted matches, or ``None`` when two accepted
    matches irreconcilably conflict with each other."""
    external_ids: ExternalIds = Field(default_factory=ExternalIds)
    """ExternalIds merged from all accepted matches, enriched by mappings."""
    accepted: List[ProviderMatch] = Field(default_factory=list)
    """The subset of input matches that were accepted (did not conflict)."""
    dropped: List[ProviderMatch] = Field(default_factory=list)
    """Matches dropped because they conflicted with local signals."""
    conflicts: List[ResolutionConflict] = Field(default_factory=list)
    """Per-drop diagnostic — which provider clashed, with what, on which fields.
    Useful for surfacing disagreements to callers without re-running compare()."""
    relations: Dict[EntityRole, List[ProviderEntity]] = Field(default_factory=dict)
    """Release-variant entities collected when ``signals.include_variants=True``."""


class MetadataProvider(ABC):
    """Look a work up against an external authoritative DB.

    Routing is two-axis. ``media`` (a set of mediavocab ``MediaType``
    values) is the primary gate; ``genre_filter`` (a set of genre
    strings — typically constants from ``mediavocab.taxonomy.genre``)
    is an optional secondary gate. A provider matches when:

        (no `media` declared OR signals.medium is None OR signals.medium in self.media)
        AND
        (no `genre_filter` declared OR self.genre_filter ∩ signals.content_genres)

    Anime / manga-only providers therefore declare e.g.
    ``media = {EPISODIC_SERIES, MOVIE}`` plus
    ``genre_filter = {"anime"}`` rather than a fake
    ``MediaType.ANIME`` value (anime is a *genre*, per mediavocab spec
    axiom 2).
    """

    name: ClassVar[str] = ""
    media: ClassVar[Set[MediaType]] = set()
    genre_filter: ClassVar[Set[str]] = set()

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider has all the configuration it needs."""

    @abstractmethod
    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        """Return the single best match for ``signals``, or ``None``."""

    def matches(self, signals: Signals) -> bool:
        """Default routing test — used by ``resolve`` to gate dispatch."""
        if self.media and signals.medium and signals.medium not in self.media:
            return False
        if self.genre_filter:
            tags = set(signals.content_genres or [])
            if not (tags & self.genre_filter):
                return False
        return True

    def lookup_candidates(self, signals: Signals) -> List[ProviderMatch]:
        """Return up to N plausible matches, highest confidence first.

        Default implementation just wraps :meth:`lookup`. Override when the
        upstream API can cheaply rank multiple candidates and you want
        :func:`consolidate` to pick across providers (e.g. namesake bands,
        ambiguous person searches).
        """
        match = self.lookup(signals)
        return [match] if match is not None else []

    def list_variants(self, external_ids: ExternalIds,
                      signals: Optional[Signals] = None) -> List[ProviderEntity]:
        """Return RELEASE entities known for the given IDs.

        Called by :func:`resolve` when ``signals.include_variants=True``.
        Default returns ``[]``. Override in variant-aware providers.
        """
        return []

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        """Given some IDs, return additional cross-references this provider
        knows how to derive without a free-text search.

        Default returns ``None`` — the provider has nothing to add. Override
        when the upstream API exposes ID-keyed lookup endpoints
        (``get_artist_by_mbid``, ``lookup_by_thetvdb``, ``get_edition_by_isbn``,
        Wikidata's claim map, etc.). The returned :class:`ExternalIds` is the
        *enrichment*, not a merge — :func:`enrich` does the merge so input
        fields stay authoritative (first-writer-wins).
        """
        return None


_REGISTRY: Dict[str, MetadataProvider] = {}


def register(provider: MetadataProvider) -> MetadataProvider:
    """Register a provider instance under its ``name``."""
    if not provider.name:
        raise ValueError("provider must declare a `name` class attribute")
    _REGISTRY[provider.name] = provider
    return provider


def all_providers() -> Dict[str, MetadataProvider]:
    """Return a copy of the current registry."""
    return dict(_REGISTRY)


def active_providers(medium: Optional[MediaType] = None) -> List[MetadataProvider]:
    """Return providers whose ``is_available()`` is True.

    If ``medium`` is given, only providers whose ``media`` set includes that
    medium are returned.
    """
    out = [p for p in _REGISTRY.values() if p.is_available()]
    if medium is not None:
        out = [p for p in out if not p.media or medium in p.media]
    return out


# ---------------------------------------------------------------------------
# Match consolidation
# ---------------------------------------------------------------------------

def consolidate(matches: List[ProviderMatch], local: Signals) -> ResolveResult:
    """Merge provider matches against a local signals bag.

    Matches are consumed highest-confidence-first so a strong provider
    anchors the consensus before weaker ones get a vote. Matches that
    contradict *local* are dropped outright; matches that contradict the
    running consolidation are dropped and surface as ``signals=None`` in
    the result (``external_ids`` and ``accepted`` still reflect what was
    collected up to that point).
    """
    consolidated = local
    external = ExternalIds()
    accepted: List[ProviderMatch] = []
    dropped: List[ProviderMatch] = []
    conflicts: List[ResolutionConflict] = []
    conflict_found = False
    anchor_provider: Optional[str] = None

    # Stable sort by confidence descending — when two matches tie we keep
    # the original input order so callers retain a predictable result.
    ordered = sorted(matches, key=lambda m: m.confidence, reverse=True)

    for m in ordered:
        local_clash = compare(local, m.signals)
        if local_clash:
            dropped.append(m)
            conflicts.append(ResolutionConflict(
                provider=m.provider, against="local", fields=local_clash,
            ))
            continue
        running_clash = compare(consolidated, m.signals)
        if running_clash:
            conflict_found = True
            dropped.append(m)
            conflicts.append(ResolutionConflict(
                provider=m.provider,
                against=anchor_provider or "consolidated",
                fields=running_clash,
            ))
            continue
        consolidated = merged(consolidated, m.signals)
        enriched = m.external_ids
        for role in EntityRole:
            enriched = apply_mappings(role, enriched)
        external = external.merge(enriched)
        accepted.append(m)
        if anchor_provider is None:
            anchor_provider = m.provider

    return ResolveResult(
        signals=None if conflict_found else consolidated,
        external_ids=external,
        accepted=accepted,
        dropped=dropped,
        conflicts=conflicts,
    )


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

def _gather_candidates(provider: "MetadataProvider",
                       signals: Signals) -> List[ProviderMatch]:
    """Internal: pull this provider's candidates via the cache when its
    `lookup_candidates` is the default (single-best wrapper); otherwise call
    the override directly. Catches provider-side exceptions."""
    from metadatarr.resolve._cache import cached_lookup

    if type(provider).lookup_candidates is MetadataProvider.lookup_candidates:
        single = cached_lookup(provider, signals)
        return [single] if single is not None else []
    try:
        return provider.lookup_candidates(signals) or []
    except Exception:
        return []


def _run_pool(providers: List["MetadataProvider"],
              fn,
              max_workers: int) -> list:
    """Bounded ThreadPoolExecutor.map wrapper. Empty in → empty out."""
    from concurrent.futures import ThreadPoolExecutor

    if not providers:
        return []
    workers = max(1, min(max_workers, len(providers)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, providers))


def search(signals: Signals, *, max_workers: int = 8) -> List[ProviderMatch]:
    """Fan out to every active provider, return the ranked candidate union.

    Same fan-out plumbing as :func:`resolve` (concurrent, cached, filtered
    by `signals.medium`) but emits the raw candidate list instead of
    consolidating into one record. Sorted by ``ProviderMatch.confidence``
    descending, ties broken by provider iteration order.

    Pipeline:

    .. code-block:: python

        # equivalent to today's resolve():
        consolidate(search(signals), signals)

        # top-N for a UI list:
        search(signals)[:5]
    """
    providers = active_providers(medium=signals.medium)
    matches: List[ProviderMatch] = []
    for batch in _run_pool(providers,
                           lambda p: _gather_candidates(p, signals),
                           max_workers):
        matches.extend(batch)
    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches


def resolve(signals: Signals, *, max_workers: int = 8) -> ResolveResult:
    """Fan out to all active providers that cover *signals.medium*, consolidate.

    Providers are filtered by ``medium`` before calling ``lookup()`` so a
    music lookup never touches the TMDB movie provider, etc. Lookups run
    concurrently (bounded by *max_workers*) and pass through a cache that
    memoises both hits and misses keyed by
    ``(provider.name, signal_hash(signals))``. Providers with an empty
    ``media`` set are always included (they declare no restriction).

    When ``signals.include_variants`` is True, every active provider's
    :meth:`MetadataProvider.list_variants` is called after consolidation and
    the collected :class:`ProviderEntity` records are stored in
    ``result.relations[EntityRole.RELEASE]``.

    Returns a :class:`ResolveResult` regardless of how many providers matched.
    """
    result = consolidate(search(signals, max_workers=max_workers), signals)
    if signals.include_variants:
        providers = active_providers(medium=signals.medium)

        def _get_variants(p: "MetadataProvider") -> List[ProviderEntity]:
            try:
                return p.list_variants(result.external_ids, signals) or []
            except Exception:
                return []

        def _variant_key(ent: ProviderEntity) -> object:
            ids = ent.external_ids
            if ids.fanedit_id is not None:
                return ("fanedit", ids.fanedit_id)
            if ids.musicbrainz_release:
                return ("mbrelease", ids.musicbrainz_release)
            return ("name", ent.name)

        seen: dict = {}
        # Seed from any RELEASE relations already present in accepted matches.
        for m in result.accepted:
            for ent in m.relations.get(EntityRole.RELEASE, []):
                seen.setdefault(_variant_key(ent), ent)
        for batch in _run_pool(providers, _get_variants, max_workers):
            for ent in batch:
                seen.setdefault(_variant_key(ent), ent)
        if seen:
            result.relations[EntityRole.RELEASE] = list(seen.values())
    return result


def enrich(external_ids: ExternalIds, *,
           medium: Optional[MediaType] = None,
           apply_maps: bool = True,
           max_workers: int = 8) -> ExternalIds:
    """Given some IDs, derive more IDs by consulting every active provider.

    Each provider's :meth:`MetadataProvider.enrich` is called with
    *external_ids*. Non-None results are merged into the input via
    :meth:`ExternalIds.merge`, which is first-writer-wins — so the input's
    own IDs are preserved and providers only fill in missing slots.

    When ``apply_maps`` is true (the default), :func:`apply_mappings` is
    run for every :class:`EntityKind` after merging. Today mappings only
    fire during :func:`consolidate`; this lets ID-only callers benefit too.

    Use cases:

    - You have an MBID and want the Wikidata Q-id and IMDb tt-id.
    - You have a TVDB id and want the IMDb id (via TVmaze's
      ``lookup_by_thetvdb``).
    - You have an ISBN and want the OpenLibrary OLID.
    """
    from metadatarr.resolve._cache import cached_enrich

    providers = active_providers(medium=medium)
    out = external_ids.model_copy(deep=True)

    def _call(p: "MetadataProvider") -> Optional[ExternalIds]:
        try:
            return cached_enrich(p, external_ids)
        except Exception:
            return None

    for enrichment in _run_pool(providers, _call, max_workers):
        if enrichment is not None:
            out = out.merge(enrichment)

    if apply_maps:
        for role in EntityRole:
            out = apply_mappings(role, out)
    return out
