"""SEC-005: the deployment security posture (API docs exposure + Secure session
cookie) is driven by the explicit ENVIRONMENT setting, decoupled from the
LOG_JSON log-format flag.

On main these behaviors were keyed directly off settings.log_json, so a
production deploy that left LOG_JSON at its default served /docs publicly and
emitted the OAuth session cookie without Secure, while a dev shipping JSON logs
over HTTP had its cookie silently stripped.

Settings() re-reads the environment at instantiation, so monkeypatching env vars
and constructing a fresh cfg.Settings() exercises the property without reloading
app.core.config (which would replace the singleton conftest points at the test
DB). See test_phase_273_session_https_only.py for the same pattern.

Every test here fails on main: Settings had no `is_production` property
(AttributeError), and the decoupling assertions contradict the old log_json
coupling.
"""

import pytest


def _settings(monkeypatch, *, environment=None, log_json=None):
    if environment is None:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("ENVIRONMENT", environment)
    if log_json is None:
        monkeypatch.delenv("LOG_JSON", raising=False)
    else:
        monkeypatch.setenv("LOG_JSON", "true" if log_json else "false")
    from app.core import config as cfg

    return cfg.Settings()


def test_explicit_production_sets_posture_even_without_log_json(monkeypatch):
    """ENVIRONMENT=production hardens the posture even when LOG_JSON is false —
    the exact case that left /docs open and the cookie insecure on main."""
    s = _settings(monkeypatch, environment="production", log_json=False)
    assert s.log_json is False
    assert s.is_production is True


def test_explicit_development_overrides_log_json(monkeypatch):
    """The decoupling: a dev/CI cluster shipping JSON logs no longer inherits
    the production posture (https_only=True over HTTP would strip the cookie)."""
    s = _settings(monkeypatch, environment="development", log_json=True)
    assert s.log_json is True
    assert s.is_production is False


def test_backward_compat_log_json_without_environment(monkeypatch):
    """Unset ENVIRONMENT + LOG_JSON=true keeps the hardened posture existing
    deployments relied on — no silent downgrade."""
    s = _settings(monkeypatch, environment=None, log_json=True)
    assert s.environment is None
    assert s.is_production is True


def test_empty_environment_normalizes_to_none(monkeypatch):
    """fix(#441): compose passes ENVIRONMENT through as "${ENVIRONMENT:-}", so
    an operator who never set it delivers "" — that must behave exactly like
    unset (LOG_JSON fallback), not fail the Literal validation at boot."""
    s = _settings(monkeypatch, environment="", log_json=False)
    assert s.environment is None
    assert s.is_production is False

    s = _settings(monkeypatch, environment="", log_json=True)
    assert s.environment is None
    assert s.is_production is True


def test_default_dev_posture(monkeypatch):
    s = _settings(monkeypatch, environment=None, log_json=False)
    assert s.is_production is False


def test_docs_gating_follows_is_production(monkeypatch):
    """The FastAPI docs_url expression in main.py keys off is_production."""
    prod = _settings(monkeypatch, environment="production", log_json=False)
    dev = _settings(monkeypatch, environment="development", log_json=True)
    assert (None if prod.is_production else "/docs") is None
    assert (None if dev.is_production else "/docs") == "/docs"


def test_invalid_environment_rejected(monkeypatch):
    """ENVIRONMENT is a Literal — typos fail fast instead of silently mapping to
    a posture."""
    from pydantic import ValidationError

    from app.core import config as cfg

    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("LOG_JSON", raising=False)
    with pytest.raises(ValidationError):
        cfg.Settings()
