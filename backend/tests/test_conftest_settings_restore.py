"""A test that rebinds the config singleton leaves no app module holding its copy."""

import sys
import types

import app.core.config as cfg_mod
import tests.conftest as conftest


def test_a_module_that_bound_a_rebound_settings_gets_the_original_back(monkeypatch):
    original = cfg_mod.settings
    module = types.ModuleType("app.settings_restore_probe")
    monkeypatch.setitem(sys.modules, module.__name__, module)

    restore = conftest._restore_process_global_config.__wrapped__()
    next(restore)
    try:
        # What a tenancy test does: rebind the singleton, then import a module
        # for the first time, which binds the rebound object.
        cfg_mod.settings = cfg_mod.Settings()
        module.settings = cfg_mod.settings
    finally:
        restore.close()

    assert cfg_mod.settings is original
    assert module.settings is original
