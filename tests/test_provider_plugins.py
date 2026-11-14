"""Provider plugins: entry points in the ``metadatarr.providers`` group.

A throwaway distribution (``.dist-info`` with ``entry_points.txt`` plus its
modules) is placed on ``sys.path`` so the real ``importlib.metadata``
discovery runs; nothing is patched on the discovery side.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import textwrap

import pytest

from mediavocab import MediaType
from mediavocab.models import ExternalIds
from mediavocab.models.signals import Signals

from metadatarr.resolve import base
from metadatarr.resolve.providers import _plugins

GOOD_MODULE = textwrap.dedent('''
    from mediavocab import MediaType
    from mediavocab.models import ExternalIds
    from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register

    class FakeProvider(MetadataProvider):
        name = "fake_plugin"
        media = {MediaType.BOOK}

        def is_available(self):
            return True

        def lookup(self, signals):
            return ProviderMatch(provider=self.name, confidence=0.9,
                                 signals=signals,
                                 external_ids=ExternalIds(isbn_13="9780000000002"))

    register(FakeProvider())
''')

CALLABLE_MODULE = textwrap.dedent('''
    from metadatarr.resolve.base import MetadataProvider, register

    class CallProvider(MetadataProvider):
        name = "fake_callable_plugin"
        def is_available(self):
            return False
        def lookup(self, signals):
            return None

    def setup():
        register(CallProvider())
''')

PARTIAL_MODULE = textwrap.dedent('''
    from metadatarr.resolve.base import MetadataProvider, register

    class Half(MetadataProvider):
        name = "half_registered"
        def is_available(self):
            return True
        def lookup(self, signals):
            return None

    register(Half())
    raise RuntimeError("died after registering")
''')

EXIT_MODULE = "raise SystemExit(3)\n"

INTERRUPT_MODULE = "raise KeyboardInterrupt\n"

OVERRIDE_MODULE = textwrap.dedent('''
    from metadatarr.resolve.base import MetadataProvider, register

    class Impostor(MetadataProvider):
        name = "builtin_like"
        def is_available(self):
            return True
        def lookup(self, signals):
            return None

    register(Impostor())
''')

CLASS_MODULE = textwrap.dedent('''
    from metadatarr.resolve.base import MetadataProvider

    class NeverRegistered(MetadataProvider):
        name = "never_registered"
        def is_available(self):
            return True
        def lookup(self, signals):
            return None
''')

REMOVE_MODULE = textwrap.dedent('''
    from metadatarr.resolve import base

    base._REGISTRY.pop("builtin_like")
''')

JUNK_MODULE = textwrap.dedent('''
    from metadatarr.resolve import base

    base._REGISTRY["junk"] = object()
    base._REGISTRY["builtin_like"] = "not a provider"
''')

BROKEN_MODULE = "raise RuntimeError('plugin exploded')\n"


def _make_dist(root, dist, version, entry_points, modules):
    info = root / f"{dist}-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {dist}\nVersion: {version}\n")
    lines = "\n".join(f"{k} = {v}" for k, v in entry_points.items())
    (info / "entry_points.txt").write_text(f"[metadatarr.providers]\n{lines}\n")
    for mod, src in modules.items():
        (root / f"{mod}.py").write_text(src)


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    """Isolated registry + plugin state; restored afterwards."""
    monkeypatch.setattr(base, "_REGISTRY", {})
    monkeypatch.delenv(_plugins.DISABLE_ENV, raising=False)
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    for mod in ("fakeplug_good", "fakeplug_call", "fakeplug_broken",
                "fakeplug_partial", "fakeplug_exit", "fakeplug_interrupt",
                "fakeplug_override", "fakeplug_class", "fakeplug_remove",
                "fakeplug_junk"):
        sys.modules.pop(mod, None)
    monkeypatch.undo()
    _plugins.load_plugins(force=True)


def test_plugin_provider_registered_and_resolvable(plugin_env):
    _make_dist(plugin_env, "fakeplug-good", "1.2.3",
               {"good": "fakeplug_good"}, {"fakeplug_good": GOOD_MODULE})
    status = _plugins.load_plugins(force=True)

    assert [(s.name, s.distribution, s.version, s.error) for s in status] == [
        ("good", "fakeplug-good", "1.2.3", None)]
    assert "fake_plugin" in base.all_providers()
    assert [p.name for p in base.active_providers(MediaType.BOOK)] == ["fake_plugin"]
    # Same routing as built-ins: a movie query never reaches the book plugin.
    assert base.active_providers(MediaType.MOVIE) == []
    res = base.resolve(Signals(title="Dune", medium=MediaType.BOOK))
    assert res.external_ids.isbn_13 == "9780000000002"


def test_callable_entry_point_is_called(plugin_env):
    _make_dist(plugin_env, "fakeplug-call", "0.1",
               {"call": "fakeplug_call:setup"}, {"fakeplug_call": CALLABLE_MODULE})
    status = _plugins.load_plugins(force=True)
    assert status[0].error is None
    assert "fake_callable_plugin" in base.all_providers()
    # Gating applies: an unavailable plugin provider is not active.
    assert base.active_providers() == []


def test_broken_plugin_is_logged_and_skipped(plugin_env, caplog):
    _make_dist(plugin_env, "fakeplug-good", "1.0",
               {"good": "fakeplug_good", "broken": "fakeplug_broken"},
               {"fakeplug_good": GOOD_MODULE, "fakeplug_broken": BROKEN_MODULE})
    with caplog.at_level(logging.ERROR, logger="metadatarr.resolve.providers"):
        status = {s.name: s for s in _plugins.load_plugins(force=True)}

    assert status["broken"].error and "plugin exploded" in status["broken"].error
    assert status["good"].error is None
    assert "fake_plugin" in base.all_providers()
    assert any("broken" in r.getMessage() and "plugin exploded" in r.getMessage()
               for r in caplog.records)


def test_disable_switch_skips_plugins(plugin_env, monkeypatch):
    _make_dist(plugin_env, "fakeplug-good", "1.0",
               {"good": "fakeplug_good"}, {"fakeplug_good": GOOD_MODULE})
    monkeypatch.setenv(_plugins.DISABLE_ENV, "1")
    assert _plugins.load_plugins(force=True) == []
    assert "fake_plugin" not in base.all_providers()
    assert "fakeplug_good" not in sys.modules


def test_plugins_load_once(plugin_env):
    _make_dist(plugin_env, "fakeplug-good", "1.0",
               {"good": "fakeplug_good"}, {"fakeplug_good": GOOD_MODULE})
    _plugins.load_plugins(force=True)
    base._REGISTRY.clear()
    _plugins.load_plugins()
    assert base.all_providers() == {}


def test_providers_route_lists_plugins(plugin_env):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from metadatarr.server.app import create_app

    _make_dist(plugin_env, "fakeplug-good", "1.0",
               {"good": "fakeplug_good", "broken": "fakeplug_broken"},
               {"fakeplug_good": GOOD_MODULE, "fakeplug_broken": BROKEN_MODULE})
    _plugins.load_plugins(force=True)
    body = TestClient(create_app()).get("/providers").json()
    plugins = {p["name"]: p for p in body["plugins"]}
    assert plugins["good"]["distribution"] == "fakeplug-good"
    assert plugins["good"]["version"] == "1.0"
    assert plugins["good"]["error"] is None
    assert "plugin exploded" in plugins["broken"]["error"]
    assert [p["name"] for p in body["providers"]] == ["fake_plugin"]


class _Raising(base.MetadataProvider):
    name = "raising_availability"

    def is_available(self):
        raise RuntimeError("config file unreadable")

    def lookup(self, signals):
        return None


class _Builtin(base.MetadataProvider):
    name = "builtin_like"

    def is_available(self):
        return True

    def lookup(self, signals):
        return None


def test_raising_is_available_is_logged_once_and_treated_as_unavailable(plugin_env, caplog, monkeypatch):
    monkeypatch.setattr(base, "_AVAILABILITY_FAILED", set())
    base.register(_Raising())
    base.register(_Builtin())
    with caplog.at_level(logging.ERROR, logger="metadatarr.resolve"):
        first = base.active_providers()
        second = base.active_providers(MediaType.MOVIE)

    assert [p.name for p in first] == ["builtin_like"]
    assert [p.name for p in second] == ["builtin_like"]
    logged = [r for r in caplog.records if "raising_availability" in r.getMessage()]
    assert len(logged) == 1
    assert "config file unreadable" in logged[0].getMessage()


def test_plugin_cannot_replace_an_existing_provider(plugin_env, caplog):
    builtin = base.register(_Builtin())
    _make_dist(plugin_env, "fakeplug-override", "1.0",
               {"override": "fakeplug_override"}, {"fakeplug_override": OVERRIDE_MODULE})
    with caplog.at_level(logging.WARNING, logger="metadatarr.resolve.providers"):
        status = _plugins.load_plugins(force=True)

    assert base.all_providers()["builtin_like"] is builtin
    warning = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning) == 1
    assert "Impostor" in warning[0] and "_Builtin" in warning[0] and "builtin_like" in warning[0]
    assert "refused" in status[0].error and "1 existing" in status[0].error


def test_entry_point_naming_a_provider_class_reports_that_nothing_registered(plugin_env):
    _make_dist(plugin_env, "fakeplug-class", "1.0",
               {"cls": "fakeplug_class:NeverRegistered"}, {"fakeplug_class": CLASS_MODULE})
    status = _plugins.load_plugins(force=True)

    assert status[0].error == "registered no providers"
    assert base.all_providers() == {}


def test_plugin_that_removes_a_builtin_gets_it_back(plugin_env, caplog):
    builtin = base.register(_Builtin())
    _make_dist(plugin_env, "fakeplug-remove", "1.0",
               {"remove": "fakeplug_remove"}, {"fakeplug_remove": REMOVE_MODULE})
    with caplog.at_level(logging.WARNING, logger="metadatarr.resolve.providers"):
        _plugins.load_plugins(force=True)

    assert base.all_providers()["builtin_like"] is builtin
    assert any("removed provider 'builtin_like'" in r.getMessage() and r.levelno == logging.WARNING
               for r in caplog.records)


def test_plugin_that_removes_a_builtin_reports_it_in_its_status(plugin_env):
    base.register(_Builtin())
    _make_dist(plugin_env, "fakeplug-remove", "1.0",
               {"remove": "fakeplug_remove"}, {"fakeplug_remove": REMOVE_MODULE})
    status = _plugins.load_plugins(force=True)

    assert status[0].error is not None
    assert "removed 1 built-in provider(s); restored" in status[0].error


def test_non_provider_objects_are_dropped_and_reported(plugin_env):
    builtin = base.register(_Builtin())
    _make_dist(plugin_env, "fakeplug-junk", "1.0",
               {"junk": "fakeplug_junk"}, {"fakeplug_junk": JUNK_MODULE})
    status = _plugins.load_plugins(force=True)

    assert "not MetadataProvider" in status[0].error
    assert base.all_providers() == {"builtin_like": builtin}
    assert base.active_providers() == [builtin]


def test_plugin_that_registers_then_raises_is_unregistered(plugin_env):
    kept = base.register(_Builtin())
    _make_dist(plugin_env, "fakeplug-partial", "1.0",
               {"partial": "fakeplug_partial"}, {"fakeplug_partial": PARTIAL_MODULE})
    status = _plugins.load_plugins(force=True)

    assert "died after registering" in status[0].error
    assert base.all_providers() == {"builtin_like": kept}


def test_systemexit_from_a_plugin_does_not_abort_loading(plugin_env):
    _make_dist(plugin_env, "fakeplug-exit", "1.0",
               {"a_exit": "fakeplug_exit", "b_good": "fakeplug_good"},
               {"fakeplug_exit": EXIT_MODULE, "fakeplug_good": GOOD_MODULE})
    status = {s.name: s for s in _plugins.load_plugins(force=True)}

    assert "SystemExit" in status["a_exit"].error
    assert status["b_good"].error is None
    assert "fake_plugin" in base.all_providers()


def test_keyboard_interrupt_from_a_plugin_propagates(plugin_env):
    _make_dist(plugin_env, "fakeplug-interrupt", "1.0",
               {"interrupt": "fakeplug_interrupt"},
               {"fakeplug_interrupt": INTERRUPT_MODULE})
    with pytest.raises(KeyboardInterrupt):
        _plugins.load_plugins(force=True)


def test_plugin_loads_on_the_real_startup_path(tmp_path):
    """A fresh interpreter that only runs ``import metadatarr`` sees the plugin."""
    _make_dist(tmp_path, "fakeplug-good", "1.0",
               {"a_exit": "fakeplug_exit", "good": "fakeplug_good"},
               {"fakeplug_exit": EXIT_MODULE, "fakeplug_good": GOOD_MODULE})
    env = dict(os.environ)
    env.pop(_plugins.DISABLE_ENV, None)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(tmp_path)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    code = (
        "import metadatarr\n"
        "from metadatarr.resolve import all_providers\n"
        "from metadatarr.resolve.providers import loaded_plugins\n"
        "print('fake_plugin' in all_providers(), "
        "sorted((s.name, s.error is None) for s in loaded_plugins()))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=str(tmp_path),
                         capture_output=True, text=True, timeout=120)

    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "True [('a_exit', False), ('good', True)]"
