"""Step 7 — voice-agent routing: verb → PlaybackType → providers.

A voice agent hears "play me Bohemian Rhapsody" or "watch Inception".
The verb collapses cleanly onto a ``PlaybackType`` (axiom 13);
filling in ``Signals.playback_type`` gates the resolver to the right
provider subset.
"""
from mediavocab import MediaType, PlaybackType, Signals
from metadatarr.resolve import resolve

# Map common verbs to a modality. Extend with your locale's verbs.
_VERB_TO_MODALITY = {
    "play":   PlaybackType.AUDIO,
    "listen": PlaybackType.AUDIO,
    "watch":  PlaybackType.VIDEO,
    "show":   PlaybackType.VIDEO,
    "read":   PlaybackType.PAGED,
    "open":   PlaybackType.PAGED,
    "launch": PlaybackType.INTERACTIVE,
}


def parse(utterance: str) -> Signals:
    """Toy parser — first word is the verb, rest is the title."""
    parts = utterance.strip().split(maxsplit=1)
    verb = parts[0].lower() if parts else ""
    title = parts[1] if len(parts) > 1 else ""
    modality = _VERB_TO_MODALITY.get(verb, PlaybackType.UNKNOWN)
    return Signals(title=title, playback_type=modality)


def main() -> None:
    utterances = [
        "play Bohemian Rhapsody",
        "watch Inception",
        "read The Hobbit",
        "show me Cowboy Bebop",
    ]
    for u in utterances:
        sig = parse(u)
        # Hint medium for the second example to pick up tvmaze etc.
        if sig.playback_type == PlaybackType.VIDEO and "Bebop" in u:
            sig = sig.model_copy(update={"medium": MediaType.EPISODIC_SERIES,
                                          "content_genres": ["anime"]})
        result = resolve(sig)
        print(f"\n\"{u}\"")
        print(f"  modality = {sig.playback_type.value if sig.playback_type else '—'}")
        print(f"  accepted: {[m.provider for m in result.accepted]}")
        ids = {k: v for k, v in result.external_ids.model_dump(exclude_none=True).items()
               if v not in (None, "", {}, [])}
        ids.pop("extra", None)
        if ids:
            short = list(ids.items())[:3]
            print(f"  ids: {dict(short)}{'…' if len(ids) > 3 else ''}")


if __name__ == "__main__":
    main()
