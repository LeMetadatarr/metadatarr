"""Step 7 — voice-agent routing: verb → PlaybackModality → providers.

A voice agent hears "play me Bohemian Rhapsody" or "watch Inception".
The verb collapses cleanly onto a ``PlaybackModality`` (axiom 13);
filling in ``Signals.modality`` gates the resolver to the right
provider subset.
"""
from mediavocab import MediaType, PlaybackModality, Signals
from metadatarr.resolve import resolve

# Map common verbs to a modality. Extend with your locale's verbs.
_VERB_TO_MODALITY = {
    "play":   PlaybackModality.AUDIO,
    "listen": PlaybackModality.AUDIO,
    "watch":  PlaybackModality.VIDEO,
    "show":   PlaybackModality.VIDEO,
    "read":   PlaybackModality.TEXT,
    "open":   PlaybackModality.TEXT,
    "launch": PlaybackModality.INTERACTIVE,
}


def parse(utterance: str) -> Signals:
    """Toy parser — first word is the verb, rest is the title."""
    parts = utterance.strip().split(maxsplit=1)
    verb = parts[0].lower() if parts else ""
    title = parts[1] if len(parts) > 1 else ""
    modality = _VERB_TO_MODALITY.get(verb, PlaybackModality.UNKNOWN)
    return Signals(title=title, modality=modality)


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
        if sig.modality == PlaybackModality.VIDEO and "Bebop" in u:
            sig = sig.model_copy(update={"medium": MediaType.EPISODIC_SERIES,
                                          "content_genres": ["anime"]})
        result = resolve(sig)
        print(f"\n\"{u}\"")
        print(f"  modality = {sig.modality.value if sig.modality else '—'}")
        print(f"  accepted: {[m.provider for m in result.accepted]}")
        ids = {k: v for k, v in result.external_ids.model_dump(exclude_none=True).items()
               if v not in (None, "", {}, [])}
        ids.pop("extra", None)
        if ids:
            short = list(ids.items())[:3]
            print(f"  ids: {dict(short)}{'…' if len(ids) > 3 else ''}")


if __name__ == "__main__":
    main()
