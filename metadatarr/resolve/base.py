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

import warnings
from abc import ABC, abstractmethod
from typing import ClassVar, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field

from metadatarr.resolve._errors import ProviderError, trap
from metadatarr.resolve.entities import (
    EntityRole,
    ProviderEntity,
    _normalize_name,
    allocate_entity_id,
)
from mediavocab.models import ExternalIds
from metadatarr.resolve.mappings import apply_mappings
from mediavocab import MediaType, PlaybackType
from mediavocab.models.signals import Signals, SignalConflict, compare_signals as compare, merge_signals as merged


class ProviderMatch(BaseModel):
    """One provider's response: what they say the work is."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    confidence: float = Field(ge=0.0, le=1.0)
    signals: Signals = Field(default_factory=Signals)
    external_ids: ExternalIds = Field(default_factory=ExternalIds)
    relations: Dict[EntityRole, List[ProviderEntity]] = Field(default_factory=dict)
    variants: List[ProviderEntity] = Field(default_factory=list)


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
    """Contribution entities collected from accepted matches."""
    variants: List[ProviderEntity] = Field(default_factory=list)
    """Release-variant entities collected when ``signals.include_variants=True``."""
    provider_errors: List[ProviderError] = Field(default_factory=list)
    """Failures swallowed during fan-out, one entry per provider that raised.

    Empty when every provider either matched or returned nothing cleanly. A
    non-empty list means a provider raised — often a sign of upstream schema
    drift — while the run continued with the remaining providers. Inspect it to
    tell "no match" apart from "the lookup broke"."""


class MetadataProvider(ABC):
    """Look a work up against an external authoritative DB.

    Routing is **three-axis** (mediavocab spec axiom 13). Each axis is
    an independent ``ClassVar[Set[X]]`` declaration; a provider
    matches when *all three* gates pass:

        (no ``media``    declared OR signals.medium   in self.media)
        AND
        (no ``modality`` declared OR signals.playback_type in self.playback_type)
        AND
        (no ``genre_filter`` declared OR self.genre_filter ∩ signals.content_genres)

    - ``media``: which ``MediaType`` values the provider serves.
    - ``modality``: which ``PlaybackType`` values (AUDIO / VIDEO /
      INTERACTIVE / TEXT / UNKNOWN). Lets a caller route a
      ``MediaType.GENERIC`` query to audio-only providers via
      ``Signals(playback_type=AUDIO)``.
    - ``genre_filter``: genre tags from ``mediavocab.taxonomy.genre``.
      Anime / manga gating uses this rather than a fake
      ``MediaType.ANIME`` (axiom 2).
    """

    name: ClassVar[str] = ""
    media: ClassVar[Set[MediaType]] = set()
    playback_type: ClassVar[Set[PlaybackType]] = set()
    genre_filter: ClassVar[Set[str]] = set()

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider has all the configuration it needs."""

    @abstractmethod
    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        """Return the single best match for ``signals``, or ``None``."""

    def matches(self, signals: Signals) -> bool:
        """Default three-axis routing test — used by ``resolve`` to gate dispatch."""
        if self.media and signals.medium and signals.medium not in self.media:
            return False
        if self.playback_type and signals.playback_type and signals.playback_type not in self.playback_type:
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

def _aggregate_relations(
    accepted: List[ProviderMatch],
) -> Dict[EntityRole, List[ProviderEntity]]:
    """Collect relation entities from accepted matches, deduped per role.

    Two providers that point at the same entity (same canonical external id, or
    same name when no id is known) collapse into one :class:`ProviderEntity`
    with their ``external_ids`` and aliases merged.
    """
    out: Dict[EntityRole, List[ProviderEntity]] = {}
    for match in accepted:
        for role, entities in match.relations.items():
            bucket = out.setdefault(role, [])
            index: Dict[str, ProviderEntity] = {
                allocate_entity_id(role, name=e.name, external_ids=e.external_ids): e
                for e in bucket
            }
            for ent in entities:
                eid = allocate_entity_id(
                    role, name=ent.name, external_ids=ent.external_ids
                )
                existing = index.get(eid)
                if existing is None:
                    index[eid] = ent
                    bucket.append(ent)
                else:
                    existing.external_ids = existing.external_ids.merge(ent.external_ids)
                    if ent.name and ent.name != existing.name:
                        existing.merge_alias(ent.name)
    return out


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
        relations=_aggregate_relations(accepted),
    )


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

def _gather_candidates(provider: "MetadataProvider",
                       signals: Signals,
                       sink: Optional[List[ProviderError]] = None,
                       ) -> List[ProviderMatch]:
    """Internal: pull this provider's candidates via the cache when its
    `lookup_candidates` is the default (single-best wrapper); otherwise call
    the override directly. A provider that raises is trapped: the failure is
    logged, recorded in ``sink``, and this returns ``[]``."""
    from metadatarr.resolve._cache import cached_lookup

    if type(provider).lookup_candidates is MetadataProvider.lookup_candidates:
        with trap(provider.name, "lookup", sink):
            single = cached_lookup(provider, signals)
            return [single] if single is not None else []
        return []
    with trap(provider.name, "candidates", sink):
        return provider.lookup_candidates(signals) or []
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


def candidates(signals: Signals, *, max_workers: int = 8,
               sink: Optional[List[ProviderError]] = None,
               ) -> List[ProviderMatch]:
    """Fan out to every active provider, return the ranked candidate union.

    The raw, *un-consolidated* counterpart to :func:`resolve`. Use this when
    you want to see every provider's vote individually — a disambiguation UI,
    a "did you mean…" list, or your own custom merge policy. Use
    :func:`resolve` instead when you just want the single merged record.

    Same fan-out plumbing as :func:`resolve` (concurrent, cached, filtered
    by ``signals.medium``) but emits the raw candidate list instead of
    consolidating into one record. Sorted by ``ProviderMatch.confidence``
    descending, ties broken by provider iteration order.

    .. code-block:: python

        # equivalent to resolve():
        consolidate(candidates(signals), signals)

        # top-N for a UI list:
        candidates(signals)[:5]
    """
    providers = active_providers(medium=signals.medium)
    matches: List[ProviderMatch] = []
    for batch in _run_pool(providers,
                           lambda p: _gather_candidates(p, signals, sink),
                           max_workers):
        matches.extend(batch)
    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches


def search(signals: Signals, *, max_workers: int = 8) -> List[ProviderMatch]:
    """Deprecated alias for :func:`candidates`.

    Kept for backward compatibility; new code should call
    :func:`candidates`, which names the return value (ranked candidate
    matches) more clearly. Behaviour is identical.
    """
    warnings.warn(
        "search() is deprecated; use candidates() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return candidates(signals, max_workers=max_workers)


# Work/release-identity ExternalIds fields, in priority order.
#
# Variants are work-shaped entities (``EntityRole.OTHER``): they name a cut,
# edition, or release of a work, not a person, artist, label, or channel. The
# per-role ladder in ``entities._dominant_external_id`` is scoped to
# contribution roles and does not cover this shape, so variant keying gets
# its own, local, work-level ladder here instead of reusing that function.
_VARIANT_ID_FIELDS: Tuple[str, ...] = (
    "fanedit_id",                 # fan-edit / alternate-cut identifier
    "musicbrainz_release",        # a specific release: one edition of a release-group
    "musicbrainz_release_group",  # a release-group: a work grouping across editions
    "musicbrainz_recording",      # a specific recording: one take of a work
    "musicbrainz_work",           # the abstract musical work
    "imdb",                       # IMDb title id (movie / show / episode)
    "tmdb_movie",                 # TMDB movie id
    "tmdb_tv",                    # TMDB tv-show id
    "tvdb",                       # TheTVDB series/episode id
    "tvmaze",                     # TVmaze show id
    "trakt_id",                   # Trakt title id
    "discogs_release",            # a Discogs release: a specific pressing/edition
    "isbn_13",                    # book edition identifier
    "isbn_10",                    # book edition identifier (legacy format)
    "olid",                       # Open Library edition/work id
    "google_books_id",            # Google Books volume id
    "bluray_com_id",              # Blu-ray.com edition id
    "dvdcompare_id",              # DVDCompare edition id
    "audible_asin",               # Audible edition id
    "librivox_id",                # LibriVox recording id
    "podcast_index_id",           # Podcast Index feed id
    "apple_podcast_id",           # Apple Podcasts feed id
    "listen_notes_id",            # ListenNotes feed id
    "anilist_id",                 # AniList media id
    "mal_id",                     # MyAnimeList media id
    "anidb_id",                   # AniDB media id
    "audiodb_album_id",           # TheAudioDB album id
    "audiodb_track_id",           # TheAudioDB track id
    "metal_archives_release",     # Metal Archives release id
    "metal_archives_song",        # Metal Archives song id
    "opencritic_id",              # OpenCritic game id
    "rawg_id",                    # RAWG game id
    "igdb_id",                    # IGDB game id
    "iheart_podcast_id",          # iHeart podcast feed id
    "iheart_episode_id",          # iHeart episode id
    "iheart_track_id",            # iHeart track id
    "iheart_playlist_id",         # iHeart playlist id
)


def _variant_key(ent: ProviderEntity) -> object:
    """Identity key for deduplicating :class:`ProviderEntity` variants.

    Keys by the first populated field of :data:`_VARIANT_ID_FIELDS` (the
    work/release-identity ladder). If none of those is set but some other
    external id is populated, keys by the first populated field in the
    model's declared field order instead of collapsing to name. Only when
    the entity carries no external ids at all does this fall back to the
    normalized name, reusing the same normalization
    :func:`metadatarr.resolve.entities.allocate_entity_id` uses for its
    name-seeded path.

    Two variants with different dominant-id fields that happen to share a
    secondary id remain distinct here — that overlap is a mappings concern,
    not this key's.
    """
    ids = ent.external_ids
    for field_name in _VARIANT_ID_FIELDS:
        value = getattr(ids, field_name, None)
        if value is not None:
            return (field_name, value)
    for field_name in type(ids).model_fields:
        if field_name == "extra":
            continue
        value = getattr(ids, field_name, None)
        if value is not None:
            return (field_name, value)
    return ("name", _normalize_name(ent.name))


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
    ``result.variants``.

    Returns a :class:`ResolveResult` regardless of how many providers matched.

    This is the **headline entry point**: it gives you one merged answer. When
    you need the individual provider votes instead (disambiguation UI, custom
    merge policy), call :func:`candidates`.
    """
    sink: List[ProviderError] = []
    result = consolidate(
        candidates(signals, max_workers=max_workers, sink=sink), signals)
    result.provider_errors = sink
    if signals.include_variants:
        providers = active_providers(medium=signals.medium)

        def _get_variants(p: "MetadataProvider") -> List[ProviderEntity]:
            with trap(p.name, "variants", sink):
                return p.list_variants(result.external_ids, signals) or []
            return []

        seen: dict = {}
        # Seed from any variants already present in accepted matches.
        for m in result.accepted:
            for ent in m.variants:
                seen.setdefault(_variant_key(ent), ent)
        for batch in _run_pool(providers, _get_variants, max_workers):
            for ent in batch:
                seen.setdefault(_variant_key(ent), ent)
        if seen:
            result.variants = list(seen.values())
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
        with trap(p.name, "enrich"):
            return cached_enrich(p, external_ids)
        return None

    for enrichment in _run_pool(providers, _call, max_workers):
        if enrichment is not None:
            out = out.merge(enrichment)

    if apply_maps:
        for role in EntityRole:
            out = apply_mappings(role, out)
    return out
