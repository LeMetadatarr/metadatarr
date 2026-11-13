# SPDX-License-Identifier: Apache-2.0
"""Look items, credits and people up by an external identifier.

Where :mod:`metadatarr.resolve` answers "what is this?" from a title,
the catalogue answers "tell me about this id": an item's details with its
children one level down, the people credited on it, and a person with their
filmography. See :mod:`metadatarr.catalog.base` for routing, timeouts and the
cache, and :mod:`metadatarr.catalog.shapes` for the answer shapes.
"""
from metadatarr.catalog.base import (  # noqa: F401
    CHILD_KIND,
    KINDS,
    Answer,
    CatalogSource,
    InvalidId,
    NotSupported,
    all_sources,
    ask,
    capabilities_of,
    mark_truncated,
    register_source,
    reset_cache,
)
from metadatarr.catalog.roles import ROLES, is_standard_role, normalise_role  # noqa: F401
from metadatarr.catalog.shapes import Credit, Item, Person, PersonDetails  # noqa: F401
import metadatarr.catalog.sources  # noqa: F401,E402
