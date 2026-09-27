"""A test that rebinds the config singleton leaves no app module holding its copy."""

import importlib
import sys
import types

import app.core.config as cfg_mod
import tests.conftest as conftest


def _run_under_restore(test_body):
    restore = conftest._restore_process_global_config.__wrapped__()
    next(restore)
    try:
        test_body()
    finally:
        restore.close()


def test_a_module_that_bound_a_rebound_settings_gets_the_original_back(monkeypatch):
    original = cfg_mod.settings
    module = types.ModuleType("app.settings_restore_probe")
    monkeypatch.setitem(sys.modules, module.__name__, module)

    def rebind_then_bind():
        cfg_mod.settings = cfg_mod.Settings()
        module.settings = cfg_mod.settings
        module.app_settings = cfg_mod.settings

    _run_under_restore(rebind_then_bind)

    assert cfg_mod.settings is original
    assert module.settings is original
    assert module.app_settings is original


def test_a_module_imported_while_rebound_gets_the_original_back(monkeypatch):
    """The test puts the singleton back itself, as a module's own restore fixture can."""
    original = cfg_mod.settings
    module = types.ModuleType("app.settings_restore_probe")

    def rebind_import_then_restore():
        cfg_mod.settings = cfg_mod.Settings()
        monkeypatch.setitem(sys.modules, module.__name__, module)
        module.app_settings = cfg_mod.settings
        cfg_mod.settings = original

    _run_under_restore(rebind_import_then_restore)

    assert module.app_settings is original


def test_a_settings_built_after_a_config_reload_gets_the_original_back(monkeypatch):
    """Reloading app.core.config makes its Settings a new class, as one test does."""
    original = cfg_mod.settings
    config_globals = dict(vars(cfg_mod))
    module = types.ModuleType("app.settings_restore_probe")
    monkeypatch.setitem(sys.modules, module.__name__, module)

    def reload_then_bind():
        importlib.reload(cfg_mod)
        module.app_settings = cfg_mod.settings

    try:
        _run_under_restore(reload_then_bind)
        assert module.app_settings is original
    finally:
        vars(cfg_mod).update(config_globals)
