# SPDX-License-Identifier: Apache-2.0
"""Packaging metadata agrees with the license text and the CI matrix."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
PROJECT = PYPROJECT["project"]


def _ci_versions():
    text = (ROOT / ".github" / "workflows" / "build-tests.yml").read_text(encoding="utf-8")
    m = re.search(r"python_versions:\s*'(\[.*?\])'", text)
    assert m, "build-tests.yml carries no python_versions matrix"
    return json.loads(m.group(1))


def _key(v):
    return tuple(int(x) for x in v.split("."))


def test_license_text_is_apache_2():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in text and "Version 2.0, January 2004" in text
    assert "MIT License" not in text


def test_license_classifier_matches_license_text():
    licenses = [c for c in PROJECT["classifiers"] if c.startswith("License ::")]
    assert licenses == ["License :: OSI Approved :: Apache Software License"]


def test_source_headers_declare_apache():
    for path in (ROOT / "metadatarr" / "server").glob("*.py"):
        head = path.read_text(encoding="utf-8").splitlines()[:1]
        if head and head[0].startswith("# SPDX-License-Identifier:"):
            assert head[0].endswith("Apache-2.0"), path


def test_requires_python_floor_is_lowest_ci_version():
    versions = _ci_versions()
    lowest = min(versions, key=_key)
    assert PROJECT["requires-python"] == f">={lowest}"


def test_python_classifiers_match_ci_matrix():
    prefix = "Programming Language :: Python :: "
    declared = sorted(
        (c[len(prefix):] for c in PROJECT["classifiers"]
         if c.startswith(prefix) and c[len(prefix):].count(".") == 1),
        key=_key)
    assert declared == sorted(_ci_versions(), key=_key)
