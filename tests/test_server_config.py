# SPDX-License-Identifier: Apache-2.0
"""Malformed ``METADATARR_*`` settings fail with an error that names the variable."""
from __future__ import annotations

import argparse

import pytest

pytest.importorskip("fastapi")

from metadatarr.cli import cmd_serve  # noqa: E402
from metadatarr.server.config import ServerConfig, ServerConfigError  # noqa: E402


@pytest.mark.parametrize("name, value", [
    ("METADATARR_RATE_LIMIT", "fast"),
    ("METADATARR_RATE_LIMIT", "10/min"),
    ("METADATARR_RATE_LIMIT", "-5"),
    ("METADATARR_RATE_LIMIT", "nan"),
    ("METADATARR_RATE_LIMIT", "inf"),
    ("METADATARR_RATE_LIMIT_BURST", "2.5"),
    ("METADATARR_RATE_LIMIT_BURST", "0"),
    ("METADATARR_RATE_LIMIT_BURST", "many"),
    ("METADATARR_MAX_UPLOAD_BYTES", "50MB"),
    ("METADATARR_MAX_UPLOAD_BYTES", "0"),
    ("METADATARR_AUTH_EXEMPT", "not-a-network"),
])
def test_malformed_setting_names_the_variable(name, value):
    with pytest.raises(ServerConfigError) as err:
        ServerConfig.from_env({name: value})
    assert name in str(err.value)


def test_error_is_still_a_value_error():
    assert issubclass(ServerConfigError, ValueError)


def test_valid_settings_are_unchanged():
    cfg = ServerConfig.from_env({
        "METADATARR_RATE_LIMIT": " 12.5 ", "METADATARR_RATE_LIMIT_BURST": "4",
        "METADATARR_MAX_UPLOAD_BYTES": "99",
    })
    assert (cfg.rate_limit_per_minute, cfg.rate_limit_burst, cfg.max_upload_bytes) == (12.5, 4, 99)


@pytest.mark.parametrize("value", ["", "  ", "0"])
def test_unset_empty_or_zero_rate_limit_means_no_limit(value):
    env = {"METADATARR_RATE_LIMIT": value} if value else {}
    assert ServerConfig.from_env(env).rate_limit_per_minute == 0


def test_defaults_when_unset():
    cfg = ServerConfig.from_env({})
    assert cfg.rate_limit_burst is None and cfg.max_upload_bytes == 50 * 1024 * 1024


def test_serve_reports_the_bad_variable_and_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setenv("METADATARR_RATE_LIMIT", "fast")
    code = cmd_serve(argparse.Namespace(host="127.0.0.1", port=0))
    assert code == 1
    assert "METADATARR_RATE_LIMIT" in capsys.readouterr().err
