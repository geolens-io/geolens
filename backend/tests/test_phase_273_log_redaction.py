"""SEC-03: Sensitive fields are redacted by a structlog processor.

Pins the v13.13 closure of M-65. Even if a developer accidentally logs
`logger.info("attempt", token=jwt)`, the token is redacted before
reaching stdout / log aggregators.
"""

import pytest
import structlog

from app.core.logging_config import _redact_sensitive_fields, setup_logging
from tests._logging_state import preserved_logging_state


# ---------------------------------------------------------------------------
# Direct unit tests of the processor function
# ---------------------------------------------------------------------------


def test_processor_redacts_token():
    """The classic case — a token field is replaced with [REDACTED]."""
    out = _redact_sensitive_fields(None, "info", {"token": "supersecret"})
    assert out == {"token": "[REDACTED]"}


@pytest.mark.parametrize(
    "field",
    [
        "jwt",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "password_hash",
        "api_key",
        "apikey",
        "x_api_key",
        "x-api-key",
        "authorization",
        "secret",
        "client_secret",
    ],
)
def test_processor_redacts_each_denylist_field(field):
    """Every entry in the denylist is redacted."""
    out = _redact_sensitive_fields(None, "info", {field: "value"})
    assert out[field] == "[REDACTED]"


def test_processor_case_insensitive():
    """Field name matching is case-insensitive."""
    out = _redact_sensitive_fields(None, "info", {"Token": "x", "AUTHORIZATION": "y"})
    assert out["Token"] == "[REDACTED]"
    assert out["AUTHORIZATION"] == "[REDACTED]"


def test_processor_leaves_safe_fields_unchanged():
    """Non-sensitive fields pass through untouched."""
    event = {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "duration_ms": 12.5,
        "event": "request_completed",
        "status_code": 200,
    }
    expected = dict(event)
    out = _redact_sensitive_fields(None, "info", event)
    assert out == expected


def test_processor_redacts_non_string_values():
    """A sensitive field with an int value is still redacted (returns string '[REDACTED]')."""
    out = _redact_sensitive_fields(None, "info", {"token": 12345})
    assert out["token"] == "[REDACTED]"


def test_processor_does_not_recurse_into_nested_dicts():
    """Documented limitation: redaction is shallow, nested dicts are not walked.

    This test pins the trade-off — if behavior changes to recursive in the
    future, the test fails and forces a deliberate change.
    """
    out = _redact_sensitive_fields(None, "info", {"nested": {"token": "secret"}})
    # Top-level "nested" is not in the denylist; its inner "token" is left as-is
    assert out == {"nested": {"token": "secret"}}


def test_processor_handles_empty_dict():
    """Empty event_dict returns empty dict."""
    out = _redact_sensitive_fields(None, "info", {})
    assert out == {}


# ---------------------------------------------------------------------------
# Integration test: full setup_logging chain + structlog logger
# ---------------------------------------------------------------------------


@pytest.fixture
def restore_logging_state():
    """Undo the global logging state the test below leaves behind.

    fix(#1064): `setup_logging()` replaces the root handlers and sets
    `cache_logger_on_first_use=True`, and nothing here put either back — so
    every test after this one in the same worker inherited both. That is the
    leaked-global class this file's own subject matter is about, and the
    caching half is what makes a later `capture_logs()` see nothing.

    The call itself has to stay in the test body: pytest swaps
    `sys.stdout`/`stderr` for the call phase only, so a handler created during
    fixture setup binds to a stream capsys is not capturing. Saving here and
    restoring on teardown is the part that can live in a fixture.

    fix(#1064 codex r1/r2): restores the previous structlog config rather than
    calling `reset_defaults()` — the library default drops
    `_redact_sensitive_fields` and the stdlib routing — and covers the three
    uvicorn loggers `setup_logging()` also rewrites, not just root. Both live
    in `preserved_logging_state()` so there is one shape to be wrong.
    """
    with preserved_logging_state():
        yield


def test_integration_token_redacted_in_log_output(capsys, restore_logging_state):
    """End-to-end: configure structlog via setup_logging, log a token,
    verify the raw token does NOT appear and [REDACTED] DOES."""
    setup_logging(json_logs=True, log_level="INFO")

    logger = structlog.stdlib.get_logger("test.redaction")
    logger.info("auth_attempt", token="my-supersecret-jwt-token-value", user_id="alice")

    captured = capsys.readouterr()
    out = captured.out + captured.err  # log destination depends on handler config

    # The raw token must NOT appear
    assert "my-supersecret-jwt-token-value" not in out, (
        f"SEC-03 FAILED: raw token leaked into log output:\n{out}"
    )
    # The redaction marker must appear
    assert "[REDACTED]" in out, (
        f"SEC-03 FAILED: [REDACTED] marker missing from log output:\n{out}"
    )
    # Non-sensitive fields still appear
    assert "alice" in out
