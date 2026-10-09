"""Step 10 — read provider diagnostics off a result.

A provider that raises during fan-out never breaks a resolve: the failure is
logged and the run continues with whatever the other providers returned. Each
swallowed failure is also recorded on ``ResolveResult.provider_errors`` as a
``ProviderError`` (``provider``, ``stage``, ``error_type``, ``message``), so a
``KeyError`` from a changed upstream response is distinguishable from an honest
"no match".

To make the effect visible offline, this registers a provider whose ``lookup``
raises, then resolves and prints the recorded diagnostics.
"""
from typing import Optional

from mediavocab import MediaType, Signals
from metadatarr.resolve import resolve
from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register


class _BrokenProvider(MetadataProvider):
    """Stands in for a provider whose upstream response changed shape."""

    name = "broken_demo"
    media = {MediaType.MOVIE}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        raise KeyError("release_date")


def main() -> None:
    register(_BrokenProvider())

    result = resolve(Signals(title="Inception", medium=MediaType.MOVIE))

    print(f"Accepted matches: {len(result.accepted)}")
    print(f"Provider errors:  {len(result.provider_errors)}")
    for err in result.provider_errors:
        print(f"  ! {err.provider:<16} {err.stage:<10} "
              f"{err.error_type}: {err.message}")

    if not result.provider_errors:
        print("\nEvery provider ran cleanly — nothing to diagnose.")
    else:
        print("\nA populated list points at the provider and stage that broke,")
        print("usually a sign the upstream response changed shape.")


if __name__ == "__main__":
    main()
