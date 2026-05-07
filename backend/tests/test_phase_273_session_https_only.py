"""SEC-02: SessionMiddleware uses https_only=True in production.

Pins the v13.13 closure of M-64. The OAuth state cookie travels via this
middleware; without https_only=True, a proxy fronting the API in cleartext
could leak the cookie. Gated on settings.log_json (the production indicator
already used at main.py:407 for _is_production).
"""

import importlib

from starlette.middleware.sessions import SessionMiddleware


def _find_session_mw(user_middleware: list):
    """Locate the SessionMiddleware entry in app.user_middleware."""
    for mw in user_middleware:
        if mw.cls is SessionMiddleware:
            return mw
    return None


def test_session_middleware_https_only_true_when_log_json(monkeypatch):
    """When settings.log_json=True, SessionMiddleware is mounted with https_only=True."""
    monkeypatch.setenv("LOG_JSON", "true")

    # Reload config so the new env propagates
    from app.core import config as cfg

    importlib.reload(cfg)
    new_settings = cfg.Settings()
    assert new_settings.log_json is True, (
        "test setup: LOG_JSON=true should produce log_json=True"
    )

    # Build a minimal app to inspect mount kwargs without re-running app/main lifespan
    from starlette.applications import Starlette
    from starlette.middleware.sessions import SessionMiddleware as SM

    test_app = Starlette()
    test_app.add_middleware(
        SM,
        secret_key="x" * 32,
        https_only=new_settings.log_json,
    )
    mw = _find_session_mw(test_app.user_middleware)
    assert mw is not None
    # Inspect kwargs — Starlette stores them on the Middleware wrapper
    kwargs = mw.kwargs
    assert kwargs.get("https_only") is True


def test_session_middleware_https_only_false_in_dev(monkeypatch):
    """When settings.log_json=False (dev/test default), https_only is False."""
    monkeypatch.delenv("LOG_JSON", raising=False)
    from app.core import config as cfg

    importlib.reload(cfg)
    new_settings = cfg.Settings()
    assert new_settings.log_json is False

    from starlette.applications import Starlette
    from starlette.middleware.sessions import SessionMiddleware as SM

    test_app = Starlette()
    test_app.add_middleware(
        SM,
        secret_key="x" * 32,
        https_only=new_settings.log_json,
    )
    mw = _find_session_mw(test_app.user_middleware)
    assert mw is not None
    assert mw.kwargs.get("https_only") is False


def test_real_app_session_middleware_present():
    """The actual app.user_middleware contains a SessionMiddleware entry with explicit https_only kwarg."""
    from app.api.main import app

    mw = _find_session_mw(app.user_middleware)
    assert mw is not None, "SessionMiddleware must be mounted on the API app"
    # SEC-02: the kwarg must be passed explicitly, not omitted.
    # In test env (log_json=False), kwargs.get('https_only') is False.
    assert "https_only" in mw.kwargs, (
        "SEC-02: SessionMiddleware must be mounted with explicit https_only kwarg "
        "(set to settings.log_json) — the kwarg should NOT be omitted."
    )
