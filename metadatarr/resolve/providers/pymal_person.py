"""pymal person provider — enriches person records by ``mal_person_id``."""
from __future__ import annotations

from typing import Optional

from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.providers._pymal_common import LOG, _check_available


class PymalPersonProvider(MetadataProvider):
    name = "pymal_person"

    def is_available(self) -> bool:
        return _check_available()

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return None

    def enrich(self, external_ids: ExternalIds) -> Optional[ExternalIds]:
        if not external_ids.mal_person_id:
            return None
        try:
            import pymal as _pymal
            person = _pymal.get_person(external_ids.mal_person_id)
        except Exception as exc:
            LOG.warning("pymal_person enrich failed for mal_person_id=%s: %s",
                        external_ids.mal_person_id, exc)
            return None

        extra = dict(external_ids.extra or {})
        if person.japanese_name:
            extra.setdefault("name_japanese", person.japanese_name)
        if person.birthday:
            extra.setdefault("birthday", person.birthday)
        staff_roles_count = len(getattr(person, "staff_anime_roles", []) or [])
        if staff_roles_count:
            extra.setdefault("mal_staff_roles_count", str(staff_roles_count))

        return ExternalIds(mal_person_id=external_ids.mal_person_id, extra=extra)


register(PymalPersonProvider())
