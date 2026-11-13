# SPDX-License-Identifier: Apache-2.0
"""The credit role vocabulary and the normaliser that maps provider words onto it.

Providers describe a credit in their own words ("Original Music Composer",
"Voice", "Series Composition", "instrument"). :func:`normalise_role` turns each
into one role of :data:`ROLES`. A word it does not know comes back lower-cased
with hyphens for spaces, because clients may add roles of their own;
:func:`is_standard_role` tells the two apart.
"""
from __future__ import annotations

import re
from typing import Dict, Optional

ROLES = {
    "cast": ("actor", "voice-actor", "narrator", "host", "guest", "performer", "self"),
    "writing": ("writer", "screenwriter", "author", "lyricist", "translator", "adapted-from"),
    "direction and production": ("director", "creator", "producer", "executive-producer", "showrunner",
                                 "audio-director", "sound-designer"),
    "music": ("artist", "composer", "conductor", "arranger", "producer-music", "featured-artist"),
    "craft": ("cinematographer", "editor", "illustrator", "cover-artist", "mixer", "mastering"),
    "companies": ("studio", "label", "publisher", "network", "distributor"),
}
ROLE_NAMES = frozenset(r for group in ROLES.values() for r in group)
COMPANY_ROLES = frozenset(ROLES["companies"])

_WORDS: Dict[str, str] = {
    "actor": "actor", "actress": "actor", "cast": "actor", "acting": "actor", "star": "actor",
    "starring": "actor", "co star": "actor",
    "voice": "voice-actor", "voice actor": "voice-actor", "voice actress": "voice-actor",
    "voice over": "voice-actor", "voiceover": "voice-actor", "voice cast": "voice-actor", "dub": "voice-actor",
    "seiyuu": "voice-actor",
    "narrator": "narrator", "narration": "narrator", "reader": "narrator", "read by": "narrator",
    "narrated by": "narrator",
    "host": "host", "presenter": "host", "anchor": "host", "co host": "host",
    "guest": "guest", "guest star": "guest", "guest cast": "guest",
    "performer": "performer", "vocals": "performer", "vocal": "performer", "vocalist": "performer",
    "singer": "performer", "musician": "performer", "instrument": "performer",
    "theme song performance": "performer",
    "self": "self", "himself": "self", "herself": "self", "themselves": "self",
    "writer": "writer", "written by": "writer", "story": "writer", "teleplay": "writer", "script": "writer",
    "writing": "writer", "series composition": "writer",
    "screenplay": "screenwriter", "screenwriter": "screenwriter", "screen play": "screenwriter",
    "author": "author", "novel": "author", "lyricist": "lyricist", "lyrics": "lyricist", "lyrics by": "lyricist",
    "translator": "translator", "translation": "translator",
    "adapted from": "adapted-from", "based on": "adapted-from", "source": "adapted-from",
    "original story": "adapted-from", "original creator": "adapted-from", "characters": "adapted-from",
    "director": "director", "directed by": "director", "directing": "director", "series director": "director",
    "creator": "creator", "created by": "creator",
    "producer": "producer", "produced by": "producer", "executive producer": "executive-producer",
    "exec producer": "executive-producer", "co executive producer": "executive-producer",
    "showrunner": "showrunner", "audio director": "audio-director", "sound director": "audio-director",
    "voice director": "audio-director", "dubbing director": "audio-director",
    "sound designer": "sound-designer", "sound design": "sound-designer", "sound effects": "sound-designer",
    "artist": "artist", "album artist": "artist", "primary artist": "artist", "main artist": "artist",
    "composer": "composer", "original music composer": "composer", "music": "composer", "music by": "composer",
    "score": "composer", "conductor": "conductor", "arranger": "arranger", "arranged by": "arranger",
    "orchestrator": "arranger", "instrument arranger": "arranger", "vocal arranger": "arranger",
    "music producer": "producer-music", "record producer": "producer-music",
    "featured artist": "featured-artist", "featuring": "featured-artist", "feat": "featured-artist",
    "ft": "featured-artist",
    "cinematographer": "cinematographer", "director of photography": "cinematographer",
    "dop": "cinematographer", "dp": "cinematographer", "cinematography": "cinematographer",
    "camera": "cinematographer",
    "editor": "editor", "film editor": "editor", "editing": "editor",
    "illustrator": "illustrator", "illustration": "illustrator",
    "cover artist": "cover-artist", "cover": "cover-artist", "cover art": "cover-artist",
    "design illustration": "cover-artist",
    "mixer": "mixer", "mixing": "mixer", "mixed by": "mixer", "mix": "mixer",
    "mastering": "mastering", "mastered by": "mastering", "mastering engineer": "mastering",
    "studio": "studio", "production company": "studio", "animation studio": "studio",
    "label": "label", "record label": "label", "publisher": "publisher",
    "network": "network", "channel": "network", "broadcaster": "network",
    "distributor": "distributor", "distribution": "distributor",
}


def _clean(word: object) -> str:
    text = re.sub(r"\([^)]*\)", " ", str(word)).lower().replace("_", " ").replace("-", " ").replace("/", " ")
    text = re.sub(r"[^\w ]+", " ", text)
    return " ".join(text.split())


def normalise_role(word: Optional[object], overrides: Optional[Dict[str, str]] = None, *, cast: bool = False) -> str:
    """The vocabulary role a provider's word stands for: "Voice" becomes
    ``voice-actor``, "Original Music Composer" becomes ``composer``.

    Case, hyphens, underscores, slashes and a bracketed note are ignored.
    ``overrides`` maps cleaned words to roles for one provider whose words
    mean something narrower (MusicBrainz's ``producer`` is a record producer).
    A word already in the vocabulary is kept. Any word about casting is
    ``casting``, and a voice or dub director is ``audio-director``. Only for a
    cast entry (``cast=True``) does an unknown word containing "voice" mean
    ``voice-actor``; a crew job such as "Voice Recording" stays a role of its
    own. An unknown word comes back lower-cased with hyphens for spaces. Empty
    input gives ``""``.
    """
    if not word:
        return ""
    text = _clean(word)
    if not text:
        return ""
    if overrides and text in overrides:
        return overrides[text]
    if text.replace(" ", "-") in ROLE_NAMES:
        return text.replace(" ", "-")
    if text in _WORDS:
        return _WORDS[text]
    words = text.split()
    if "casting" in words:
        return "casting"
    if "director" in words and ({"voice", "dub", "dubbing", "adr"} & set(words)):
        return "audio-director"
    if cast and "voice" in words:
        return "voice-actor"
    return text.replace(" ", "-")


def is_standard_role(role: str) -> bool:
    return role in ROLE_NAMES
