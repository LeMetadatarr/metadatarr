"""Structured diagnostics for swallowed provider failures.

The fan-out never lets one provider break a resolve, but a swallowed exception
must still be observable: logged at WARNING and recorded structurally in
``ResolveResult.provider_errors`` so upstream schema drift is not mistaken for
"no match".
"""
from typing import List, Optional

import pytest

from metadatarr.resolve import (
    ExternalIds,
    MediaType,
    MetadataProvider,
    ProviderEntity,
    ProviderError,
    ProviderMatch,
    Signals,
    resolve,
)
from metadatarr.resolve._cache import cache
from metadatarr.resolve._errors import trap
from metadatarr.resolve import mappings


@pytest.fixture(autouse=True)
def _clear_cache():
    cache().clear()
    yield
    cache().clear()


def _only(monkeypatch, *providers):
    monkeypatch.setattr(
        "metadatarr.resolve.base.active_providers",
        lambda medium=None: list(providers),
    )


class _Ok(MetadataProvider):
    name = "ok"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return ProviderMatch(
            provider=self.name, confidence=0.9,
            signals=Signals(title="X", medium=MediaType.MOVIE),
            external_ids=ExternalIds(tmdb_movie=1),
        )


class _LookupRaiser(MetadataProvider):
    name = "lookup_raiser"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        raise KeyError("title")


class _CandidatesRaiser(MetadataProvider):
    name = "candidates_raiser"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return None

    def lookup_candidates(self, signals: Signals) -> List[ProviderMatch]:
        raise ValueError("bad page")


class _VariantsRaiser(MetadataProvider):
    name = "variants_raiser"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        return None

    def list_variants(self, external_ids, signals=None) -> List[ProviderEntity]:
        raise RuntimeError("no variants endpoint")


def test_lookup_exception_recorded_in_result(monkeypatch):
    _only(monkeypatch, _LookupRaiser(), _Ok())
    result = resolve(Signals(title="X", medium=MediaType.MOVIE))
    assert result.provider_errors == [ProviderError(
        provider="lookup_raiser", stage="lookup",
        error_type="KeyError", message=result.provider_errors[0].message,
    )]
    assert result.provider_errors[0].error_type == "KeyError"
    # The healthy provider still contributes.
    assert result.external_ids.tmdb_movie == 1


def test_candidates_override_exception_recorded(monkeypatch):
    _only(monkeypatch, _CandidatesRaiser())
    result = resolve(Signals(title="X", medium=MediaType.MOVIE))
    assert len(result.provider_errors) == 1
    err = result.provider_errors[0]
    assert err.provider == "candidates_raiser"
    assert err.stage == "candidates"
    assert err.error_type == "ValueError"


def test_variants_exception_recorded(monkeypatch):
    _only(monkeypatch, _VariantsRaiser())
    result = resolve(Signals(title="X", medium=MediaType.MOVIE,
                             include_variants=True))
    stages = {(e.provider, e.stage) for e in result.provider_errors}
    assert ("variants_raiser", "variants") in stages
    assert any(e.error_type == "RuntimeError" for e in result.provider_errors)


def test_keyboard_interrupt_not_swallowed():
    with pytest.raises(KeyboardInterrupt):
        with trap("p", "lookup"):
            raise KeyboardInterrupt


def test_malformed_mappings_toml_logged(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(mappings, "_load_package_entries", lambda: [])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    bad = tmp_path / "metadatarr" / "mappings.toml"
    bad.parent.mkdir(parents=True)
    bad.write_text("this is = not [valid toml", encoding="utf-8")
    with caplog.at_level("WARNING"):
        store = mappings.reload()
    assert len(store) == 0
    assert any(str(bad) in rec.getMessage() for rec in caplog.records)
    monkeypatch.undo()
    mappings.reload()


def test_no_errors_yields_empty_list(monkeypatch):
    _only(monkeypatch, _Ok())
    result = resolve(Signals(title="X", medium=MediaType.MOVIE))
    assert result.provider_errors == []
