"""Step 2 — three-axis routing: media × modality × genre.

The resolver picks providers by gating on three orthogonal axes
(mediavocab spec axiom 13). Watch which providers fire when you change
each axis independently.
"""
from mediavocab import MediaType, PlaybackModality, Signals
from metadatarr.resolve import active_providers


def show(label: str, sig: Signals) -> None:
    matched = sorted(p.name for p in active_providers() if p.matches(sig))
    print(f"\n{label}")
    print(f"  Signals: {sig.model_dump(exclude_none=True, exclude_defaults=True)}")
    print(f"  → {matched}")


def main() -> None:
    print(f"Total active providers: {len(active_providers())}")

    # Axis 1: media
    show("MUSIC only:",
         Signals(title="x", medium=MediaType.MUSIC))
    show("EPISODIC_SERIES only:",
         Signals(title="x", medium=MediaType.EPISODIC_SERIES))

    # Axis 2: modality (orthogonal)
    show("MOVIE + AUDIO modality (\"play me a movie\"):",
         Signals(title="x", medium=MediaType.MOVIE,
                 modality=PlaybackModality.AUDIO))
    show("MOVIE + VIDEO modality (\"watch a movie\"):",
         Signals(title="x", medium=MediaType.MOVIE,
                 modality=PlaybackModality.VIDEO))

    # Axis 3: genre_filter (anime gating)
    show("EPISODIC_SERIES + anime genre:",
         Signals(title="x", medium=MediaType.EPISODIC_SERIES,
                 content_genres=["anime"]))


if __name__ == "__main__":
    main()
