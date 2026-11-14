"""Resolve a track through the music providers, TheAudioDB among them."""
from metadatarr.resolve import MediaType, Signals, active_providers


def main() -> None:
    signals = Signals(title="Around the World", artist="Daft Punk", medium=MediaType.MUSIC)
    for provider in active_providers(medium=MediaType.MUSIC):
        match = provider.lookup(signals)
        print(f"{provider.name}: {match.external_ids if match else 'no match'}")


if __name__ == "__main__":
    main()
