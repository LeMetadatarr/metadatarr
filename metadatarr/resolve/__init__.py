"""Cross-source entity resolution and metadata merging.

Two layers:

- **Models** — :class:`Signals`, :class:`ExternalIds`, :class:`ProviderEntity`,
  :class:`EntityRecord`, :class:`EntitySidecar`, :class:`ProviderMatch`.
- **Providers** — pluggable lookup backends (MusicBrainz, Wikidata, TMDB,
  arr-stack, Metal Archives, metadatarr's own Servarr-proxy clients). Each one
  self-registers on import; missing config (API key, env var) or a missing
  optional dep silently disables the provider via :meth:`is_available`.

Importing this module triggers registration of every built-in provider.
"""
from __future__ import annotations

from metadatarr.resolve._errors import ProviderError
from metadatarr.resolve.base import (
    MetadataProvider,
    ProviderMatch,
    ResolutionConflict,
    ResolveResult,
    active_providers,
    all_providers,
    candidates,
    consolidate,
    enrich,
    register,
    resolve,
    search,
)
from metadatarr.resolve.entities import (
    EntityKind,
    EntityRecord,
    EntityRole,
    EntitySidecar,
    ProviderEntity,
    allocate_entity_id,
    attach_work,
    entities_by_kind,
    entities_by_role,
    upsert_entity,
)
from mediavocab.models import ExternalIds
from mediavocab.text import ARTIST_MIN as ARTIST_FUZZY_MIN, TITLE_MIN as TITLE_FUZZY_MIN, YEAR_WINDOW as YEAR_TOLERANCE, fuzzy_ratio
from mediavocab import MediaType
from mediavocab.models.signals import RUNTIME_TOLERANCE_S, SignalConflict, Signals, compare_signals as compare, match_quality, merge_signals as merged, signal_hash

# Activate disk-backed HTTP cache if METADATARR_HTTP_CACHE is set.
from metadatarr.resolve import _http_cache as _http_cache  # noqa: F401
_http_cache.setup()

# Trigger built-in provider registration as a side effect of `from
# metadatarr.resolve import *` or `import metadatarr.resolve`.
from metadatarr.resolve import providers as _providers  # noqa: F401

__all__ = [
    # signals
    "MediaType",
    "Signals",
    "SignalConflict",
    "compare",
    "match_quality",
    "merged",
    "signal_hash",
    "fuzzy_ratio",
    "TITLE_FUZZY_MIN",
    "ARTIST_FUZZY_MIN",
    "YEAR_TOLERANCE",
    "RUNTIME_TOLERANCE_S",
    # external ids
    "ExternalIds",
    # entities
    "EntityKind",
    "EntityRole",
    "ProviderEntity",
    "EntityRecord",
    "EntitySidecar",
    "allocate_entity_id",
    "upsert_entity",
    "attach_work",
    "entities_by_kind",
    "entities_by_role",
    # providers / resolver
    "MetadataProvider",
    "ProviderMatch",
    "ProviderError",
    "ResolutionConflict",
    "ResolveResult",
    "register",
    "all_providers",
    "active_providers",
    "consolidate",
    "enrich",
    "resolve",
    "candidates",
    "search",
]
