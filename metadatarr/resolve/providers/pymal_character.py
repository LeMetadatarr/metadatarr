"""pymal character provider — enriches character records by ``mal_character_id``."""
from __future__ import annotations

from typing import Optional

from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.providers._pymal_common import LOG, _check_available


class PymalCharacterProvider(MetadataProvider):
    name = "pymal_character"

    def is_available(self) -> bool:
        return _check_available()

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return None

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        if not external_ids.mal_character_id:
            return None
        try:
            import pymal as _pymal
            char = _pymal.get_character(external_ids.mal_character_id)
        except Exception as exc:
            LOG.warning("pymal_character enrich failed for mal_character_id=%s: %s",
                        external_ids.mal_character_id, exc)
            return None

        extra = dict(external_ids.extra or {})
        if char.japanese_name:
            extra.setdefault("name_japanese", char.japanese_name)
        if char.anime_roles:
            extra.setdefault("mal_appears_in",
                             ",".join(str(r.anime_title) for r in char.anime_roles[:5]))

        return ExternalIds(mal_character_id=external_ids.mal_character_id, extra=extra)


register(PymalCharacterProvider())
