"""Resolve a series through the TV providers, TVmaze among them."""
from metadatarr.resolve import MediaType, Signals, active_providers


def main() -> None:
    signals = Signals(title="The Boys", medium=MediaType.EPISODIC_SERIES)
    for provider in active_providers(medium=MediaType.EPISODIC_SERIES):
        match = provider.lookup(signals)
        print(f"{provider.name}: {match.external_ids if match else 'no match'}")


if __name__ == "__main__":
    main()
