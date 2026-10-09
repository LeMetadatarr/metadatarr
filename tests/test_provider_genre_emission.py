"""Guard: no provider may emit a genre outside the canonical taxonomy.

Every value a provider puts in ``Signals.content_genres`` must be a member of
``mediavocab.taxonomy.KNOWN_GENRES`` — ideally referenced via a ``GENRE_*``
constant rather than a bare string literal.

The check is *static*: it parses each provider module and inspects every
``content_genres=[…]`` keyword argument, resolving both string literals and
``GENRE_*`` / ``mediavocab.taxonomy.GENRE_*`` references to their values. This
runs offline and flags a stray genre the moment it is written, without needing
to drive the provider against a live API.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import mediavocab.taxonomy as taxonomy
from mediavocab.taxonomy import KNOWN_GENRES

PROVIDERS_DIR = (
    Path(__file__).resolve().parent.parent
    / "metadatarr" / "resolve" / "providers"
)

PROVIDER_FILES = sorted(
    p for p in PROVIDERS_DIR.glob("*.py") if p.name != "__init__.py"
)

assert PROVIDER_FILES, f"no provider modules found under {PROVIDERS_DIR}"

# Map every GENRE_* constant name → its string value, for resolving references.
_GENRE_CONSTANTS = {
    name: getattr(taxonomy, name)
    for name in dir(taxonomy)
    if name.startswith("GENRE_")
}


def _resolve_genre_value(node: ast.expr):
    """Return the genre string a content_genres element refers to, or a sentinel
    object when it cannot be statically resolved (skip those — runtime data)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # GENRE_ANIME
    if isinstance(node, ast.Name) and node.id in _GENRE_CONSTANTS:
        return _GENRE_CONSTANTS[node.id]
    # taxonomy.GENRE_ANIME / genre.GENRE_ANIME
    if isinstance(node, ast.Attribute) and node.attr in _GENRE_CONSTANTS:
        return _GENRE_CONSTANTS[node.attr]
    return _UNRESOLVED


_UNRESOLVED = object()


def _content_genre_literals(tree: ast.AST):
    """Yield (lineno, resolved_value) for every statically-resolvable element of
    a ``content_genres=[…]`` keyword argument."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "content_genres":
                continue
            if not isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
                continue
            for elt in kw.value.elts:
                val = _resolve_genre_value(elt)
                if val is not _UNRESOLVED:
                    yield node.lineno, val


@pytest.mark.parametrize("path", PROVIDER_FILES, ids=lambda p: p.name)
def test_provider_emits_only_known_genres(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for lineno, value in _content_genre_literals(tree):
        assert value in KNOWN_GENRES, (
            f"{path.name}:{lineno} emits content_genres value {value!r} which "
            f"is not in mediavocab.taxonomy.KNOWN_GENRES"
        )


def test_known_genres_nonempty():
    # sanity: the guard would be vacuous if the taxonomy import broke
    assert "anime" in KNOWN_GENRES
    assert "manga" in KNOWN_GENRES
