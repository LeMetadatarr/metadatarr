# SPDX-License-Identifier: Apache-2.0
"""What the documentation tells a reader to import and follow must exist."""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGES = [ROOT / "README.md", ROOT / "AGENTS.md", *sorted((ROOT / "docs").rglob("*.md")),
         *sorted((ROOT / "examples").rglob("*.md"))]
FROM_IMPORT = re.compile(r"^[ \t]*from (metadatarr[\w.]*) import[ \t]*(\([^)]*\)|[^\n(]+)", re.M)
PLAIN_IMPORT = re.compile(r"^[ \t]*import (metadatarr[\w.]*)", re.M)
LINK = re.compile(
    r"\]\(<?([^)\s>]+)"
    r"|^[ \t]*\[[^\]\n]+\]:[ \t]*<?(\S+?)>?[ \t]*$"
    r"|<a\s[^>]*?href=[\"']([^\"']+)[\"']",
    re.M,
)
HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t#]*$", re.M)
FENCE = re.compile(r"^(```|~~~).*?^\1", re.M | re.S)


def _ids(paths):
    return [str(p.relative_to(ROOT)) for p in paths]


def _read(page):
    return page.read_text(encoding="utf-8")


def _anchors(page):
    """GitHub heading slugs of a page, headings inside code fences excluded."""
    seen, slugs = {}, set()
    for title in HEADING.findall(FENCE.sub("", _read(page))):
        slug = re.sub(r"[^\w\- ]", "", title.replace("`", "").lower()).replace(" ", "-")
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        slugs.add(slug if n == 0 else f"{slug}-{n}")
    return slugs


@pytest.mark.parametrize("page", PAGES, ids=_ids(PAGES))
def test_documented_imports_exist(page):
    text = _read(page)
    for module, names in FROM_IMPORT.findall(text):
        mod = importlib.import_module(module)
        names = re.sub(r"#[^\n]*", "", names).strip("() \t\n")
        for name in (n.split(" as ")[0].strip() for n in names.split(",") if n.strip()):
            assert hasattr(mod, name), f"{page.name}: `from {module} import {name}` does not exist"
    for module in PLAIN_IMPORT.findall(text):
        importlib.import_module(module)


@pytest.mark.parametrize("page", PAGES, ids=_ids(PAGES))
def test_relative_links_resolve(page):
    for groups in LINK.findall(_read(page)):
        target = next(g for g in groups if g)
        if re.match(r"(https?:|mailto:)", target):
            continue
        path, _, anchor = target.partition("#")
        dest = page if not path else page.parent / path
        assert dest.exists(), f"{page.name}: link to {target} is broken"
        if anchor and dest.suffix == ".md":
            assert anchor in _anchors(dest), f"{page.name}: no heading for #{anchor} in {dest.name}"
