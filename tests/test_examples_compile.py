"""Regression guard for the ``examples/`` tree.

Every example must:

1. **Parse** — no syntax errors (catches typos like a missing comma in an
   ``import`` statement).
2. **Reference real symbols** — every ``from metadatarr… import NAME`` must
   name an attribute that actually exists on that module (catches stale
   imports such as ``from metadatarr.resolve.entities import Entity`` after
   the symbol was renamed to ``ProviderEntity``).

The check is deliberately *static*: it never executes an example's body, so it
needs no network access and is immune to third-party API drift. Importing the
named metadatarr submodule is enough to verify the symbol exists, because the
resolver's submodules are import-clean and offline.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

EXAMPLE_FILES = sorted(
    p for p in EXAMPLES_DIR.rglob("*.py") if p.name != "__init__.py"
)

# Sanity: the suite must actually find the examples it claims to guard.
assert EXAMPLE_FILES, f"no example scripts found under {EXAMPLES_DIR}"


def _ids(paths):
    return [str(p.relative_to(EXAMPLES_DIR)) for p in paths]


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=_ids(EXAMPLE_FILES))
def test_example_parses(path: Path) -> None:
    """The file is syntactically valid Python."""
    source = path.read_text(encoding="utf-8")
    compile(source, str(path), "exec")  # raises SyntaxError on failure


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=_ids(EXAMPLE_FILES))
def test_example_metadatarr_imports_resolve(path: Path) -> None:
    """Every ``from metadatarr… import NAME`` names a real attribute."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if node.module != "metadatarr" and not node.module.startswith("metadatarr."):
            continue
        module = importlib.import_module(node.module)
        for alias in node.names:
            if alias.name == "*":
                continue
            assert hasattr(module, alias.name), (
                f"{path.relative_to(EXAMPLES_DIR)} imports "
                f"`{alias.name}` from `{node.module}`, which no longer exists"
            )
