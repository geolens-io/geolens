"""SEC-08 + SEC-11: Startup warnings for production-misconfig posture.

SEC-08: Warn when CORS_ALLOWED_ORIGINS is unset in production.
SEC-11: Warn when TILE_SIGNING_SECRET is unset and falls back to JWT secret.

Pins the v13.13 closure of M-72 + L-64. Operators who forget security-relevant
env vars get a loud signal at boot rather than a silent insecure default.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# SEC-08: CORS_ALLOWED_ORIGINS warning
# ---------------------------------------------------------------------------


def test_cors_warning_fires_in_production_with_empty_cors():
    """log_json=True + cors_allowed_origins='' → cors_allowed_origins_unset warning."""
    from app.api import main as main_module

    fake_settings = SimpleNamespace(log_json=True, cors_allowed_origins="")
    fake_logger = MagicMock()

    main_module._warn_if_cors_unset(fake_settings, fake_logger)

    # SEC-08: behavior assertion — fires exactly once with the canonical event
    # name. Survives refactors that change call-count details (e.g., adding
    # an unrelated info() log) but break only on actual contract change.
    fake_logger.warning.assert_called_once_with(
        "cors_allowed_origins_unset",
        message=(
            "CORS_ALLOWED_ORIGINS is empty in production (LOG_JSON=true). "
            "All origins will pass the request-origin check; this is "
            "likely a misconfiguration. Set "
            "CORS_ALLOWED_ORIGINS=<comma-separated origins> to restrict."
        ),
    )


def test_cors_warning_silent_in_dev():
    """log_json=False (dev) → no CORS warning fires regardless of value."""
    from app.api import main as main_module

    fake_settings = SimpleNamespace(log_json=False, cors_allowed_origins="")
    fake_logger = MagicMock()

    main_module._warn_if_cors_unset(fake_settings, fake_logger)

    # SEC-08: dev mode must not warn — behavior assertion uses the built-in
    # MagicMock error message which lists the offending call_args_list.
    fake_logger.warning.assert_not_called()


def test_cors_warning_silent_with_origins_configured():
    """log_json=True + cors_allowed_origins='https://app.example.com' → no warning."""
    from app.api import main as main_module

    fake_settings = SimpleNamespace(
        log_json=True, cors_allowed_origins="https://app.example.com"
    )
    fake_logger = MagicMock()

    main_module._warn_if_cors_unset(fake_settings, fake_logger)

    # SEC-08: configured origins must not warn — behavior assertion.
    fake_logger.warning.assert_not_called()


def test_cors_warning_helper_is_called_from_lifespan():
    """SEC-08 wiring: main.py source contains the helper call inside lifespan."""
    import inspect

    from app.api import main as main_module

    lifespan_src = inspect.getsource(main_module.lifespan)
    assert "_warn_if_cors_unset" in lifespan_src, (
        "SEC-08: lifespan must call _warn_if_cors_unset(settings, logger) at startup"
    )


# ---------------------------------------------------------------------------
# SEC-11: TILE_SIGNING_SECRET fallback warning
# ---------------------------------------------------------------------------


def test_tile_signing_fallback_warns_once_when_none(monkeypatch):
    """When tile_signing_secret is None, _get_signing_key warns ONCE."""
    from app.processing.tiles import signing as signing_module

    # Reset the module-level one-shot flag for this test
    monkeypatch.setattr(signing_module, "_warned_fallback", False)

    # Mock settings: tile_signing_secret=None; jwt_secret_key stays real
    monkeypatch.setattr(
        signing_module.settings, "tile_signing_secret", None, raising=False
    )

    mock_logger = MagicMock()
    monkeypatch.setattr(signing_module, "logger", mock_logger)

    # First call — warning fires with canonical event name + message kwarg.
    # SEC-11: behavior assertion against the actual structlog event name
    # operators grep for in production logs.
    signing_module._get_signing_key()
    mock_logger.warning.assert_called_once_with(
        "tile_signing_secret_fallback",
        message=(
            "TILE_SIGNING_SECRET is unset; falling back to JWT_SECRET_KEY "
            "for HMAC tile signing. Set TILE_SIGNING_SECRET to a separate "
            "secret (openssl rand -hex 32) to isolate tile-signing key "
            "rotation from JWT key rotation."
        ),
    )

    # Second call — one-shot guard: assert_called_once_with would now FAIL if
    # the warning re-fires, so re-running it on the same mock proves the
    # one-shot semantics survived the second invocation.
    # call_count: kept — one-shot regression guard requires absolute count
    # comparison across two calls; assert_called_once_with checks total-once
    # which is exactly what we want, and re-asserting it after the second
    # call captures the regression.
    signing_module._get_signing_key()
    mock_logger.warning.assert_called_once_with(
        "tile_signing_secret_fallback",
        message=(
            "TILE_SIGNING_SECRET is unset; falling back to JWT_SECRET_KEY "
            "for HMAC tile signing. Set TILE_SIGNING_SECRET to a separate "
            "secret (openssl rand -hex 32) to isolate tile-signing key "
            "rotation from JWT key rotation."
        ),
    )


def test_tile_signing_no_warn_when_configured(monkeypatch):
    """When tile_signing_secret is set, no fallback warning fires."""
    from pydantic import SecretStr

    from app.processing.tiles import signing as signing_module

    monkeypatch.setattr(signing_module, "_warned_fallback", False)
    monkeypatch.setattr(
        signing_module.settings,
        "tile_signing_secret",
        SecretStr("custom-tile-signing-secret-32chars-or-more"),
        raising=False,
    )

    mock_logger = MagicMock()
    monkeypatch.setattr(signing_module, "logger", mock_logger)

    signing_module._get_signing_key()
    # SEC-11: configured tile_signing_secret must not warn — behavior assertion.
    mock_logger.warning.assert_not_called()


def test_get_signing_key_returns_jwt_fallback_bytes(monkeypatch):
    """Behavioral regression: when tile_signing_secret=None, returned bytes
    match jwt_secret_key.encode()."""
    from app.processing.tiles import signing as signing_module

    monkeypatch.setattr(signing_module, "_warned_fallback", False)
    monkeypatch.setattr(
        signing_module.settings, "tile_signing_secret", None, raising=False
    )

    expected = signing_module.settings.jwt_secret_key.get_secret_value().encode()
    actual = signing_module._get_signing_key()
    assert actual == expected
