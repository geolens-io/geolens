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

    assert fake_logger.warning.call_count == 1, (
        f"SEC-08: cors_allowed_origins_unset warning must fire once; got "
        f"{fake_logger.warning.call_args_list}"
    )
    args, _ = fake_logger.warning.call_args
    assert args[0] == "cors_allowed_origins_unset", (
        f"SEC-08: warning key mismatch; got {args[0]!r}"
    )


def test_cors_warning_silent_in_dev():
    """log_json=False (dev) → no CORS warning fires regardless of value."""
    from app.api import main as main_module

    fake_settings = SimpleNamespace(log_json=False, cors_allowed_origins="")
    fake_logger = MagicMock()

    main_module._warn_if_cors_unset(fake_settings, fake_logger)

    assert fake_logger.warning.call_count == 0, (
        "Dev mode (log_json=False) must not trigger CORS warning"
    )


def test_cors_warning_silent_with_origins_configured():
    """log_json=True + cors_allowed_origins='https://app.example.com' → no warning."""
    from app.api import main as main_module

    fake_settings = SimpleNamespace(
        log_json=True, cors_allowed_origins="https://app.example.com"
    )
    fake_logger = MagicMock()

    main_module._warn_if_cors_unset(fake_settings, fake_logger)

    assert fake_logger.warning.call_count == 0, (
        "Configured CORS origins must not trigger the warning"
    )


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

    # First call — warning fires
    signing_module._get_signing_key()
    assert mock_logger.warning.call_count == 1, (
        f"SEC-11: first call must fire fallback warning; got "
        f"{mock_logger.warning.call_args_list}"
    )
    first_args, _ = mock_logger.warning.call_args_list[0]
    assert first_args[0] == "tile_signing_secret_fallback", (
        f"SEC-11: warning key mismatch; got {first_args[0]!r}"
    )

    # Second call — warning does NOT fire again (one-shot)
    signing_module._get_signing_key()
    assert mock_logger.warning.call_count == 1, (
        "SEC-11: warning fired more than once — one-shot guard failed"
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
    assert mock_logger.warning.call_count == 0, (
        "tile_signing_secret is configured — fallback warning must not fire"
    )


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
