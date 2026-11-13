"""Universal per-provider smoke contract.

Every registered provider — built-in or newly added — must honour the same
contract, verified here with **no network**:

- ``is_available()`` returns a ``bool`` and never raises.
- ``lookup(signals)`` returns ``ProviderMatch | None`` and never raises.

The test parametrizes over the live registry, so a new provider is picked up
automatically: drop it in ``resolve/providers/``, and it must pass this contract
or the suite goes red.

We drive ``lookup`` with an empty :class:`Signals` (no title): every provider
short-circuits to ``None`` before touching the network, which keeps the test
offline while still exercising the return-type and never-raise guarantees. The
transport-failure → ``None`` path is covered per-provider in the cassette tests.
"""
from __future__ import annotations

import pytest

import metadatarr.resolve.providers  # noqa: F401 — trigger registration
from metadatarr.resolve.base import ProviderMatch, all_providers
from mediavocab.models.signals import Signals

_PROVIDERS = sorted(all_providers().items())

# Sanity: registration must have happened, or the parametrization is vacuous.
assert _PROVIDERS, "no providers registered — import side effect failed"


@pytest.mark.parametrize("name, provider", _PROVIDERS, ids=[n for n, _ in _PROVIDERS])
def test_is_available_returns_bool_and_never_raises(name, provider):
    result = provider.is_available()
    assert isinstance(result, bool), (
        f"{name}.is_available() returned {type(result).__name__}, expected bool"
    )


@pytest.mark.parametrize("name, provider", _PROVIDERS, ids=[n for n, _ in _PROVIDERS])
def test_lookup_returns_match_or_none_and_never_raises(name, provider):
    # Empty signals → every provider returns None before any network call.
    result = provider.lookup(Signals())
    assert result is None or isinstance(result, ProviderMatch), (
        f"{name}.lookup(Signals()) returned {type(result).__name__}, "
        f"expected ProviderMatch or None"
    )


@pytest.mark.parametrize("name, provider", _PROVIDERS, ids=[n for n, _ in _PROVIDERS])
def test_lookup_candidates_returns_list_and_never_raises(name, provider):
    result = provider.lookup_candidates(Signals())
    assert isinstance(result, list), (
        f"{name}.lookup_candidates(Signals()) returned {type(result).__name__}, "
        f"expected list"
    )
    assert all(isinstance(m, ProviderMatch) for m in result)
