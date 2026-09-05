"""SEC-03: Sensitive fields are redacted by a structlog processor.

Pins the v13.13 closure of M-65. Even if a developer accidentally logs
`logger.info("attempt", token=jwt)`, the token is redacted before
reaching stdout / log aggregators.
"""

import pytest
import structlog

from app.core.logging_config import _redact_sensitive_fields
from tests._logging_state import configured_logging


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


def test_processor_recurses_into_nested_dicts():
    """fix(#1844): the deliberate change this test's predecessor demanded.

    It used to pin the opposite -- "redaction is shallow, nested dicts are not
    walked" -- as a documented CPU trade-off, and said in its own docstring
    that changing the behaviour should have to fail a test first. This is that
    change, made on purpose: `structlog.stdlib.ExtraAdder()` lifts a stdlib
    record's whole `extra` mapping into the event dict, so what sits one level
    down is decided by third-party code, not by our own call sites. Procrastinate
    puts the job's `task_kwargs` there, which on a default install is the wire
    credential itself.

    The trade-off did not disappear, it moved: the walk is gated on the value
    being a container, so a flat record still costs one isinstance per field.
    `test_processor_leaves_safe_fields_unchanged` above covers that path.
    """
    out = _redact_sensitive_fields(None, "info", {"nested": {"token": "secret"}})

    assert out == {"nested": {"token": "[REDACTED]"}}


def test_processor_scrubs_strings_inside_a_nested_container():
    """A nested string is scrubbed even under a key the denylist never matches.

    Key redaction and pattern scrubbing are complements: Procrastinate renders
    the same kwargs a second time into `call_string`, whose KEY is not
    sensitive and whose VALUE is.
    """
    out = _redact_sensitive_fields(
        None, "info", {"job": {"call_string": "run(token='secret')"}}
    )

    assert out["job"]["call_string"] == "run(token='[REDACTED]')"


def test_processor_handles_empty_dict():
    """Empty event_dict returns empty dict."""
    out = _redact_sensitive_fields(None, "info", {})
    assert out == {}


# ---------------------------------------------------------------------------
# Integration test: full setup_logging chain + structlog logger
# ---------------------------------------------------------------------------


def test_integration_token_redacted_in_log_output(capsys):
    """End-to-end: configure structlog via setup_logging, log a token,
    verify the raw token does NOT appear and [REDACTED] DOES.

    fix(#1064): `setup_logging()` replaces the root handlers and sets
    `cache_logger_on_first_use=True`, and nothing here put either back — so
    every test after this one in the same worker inherited both. That is the
    leaked-global class this file's own subject matter is about, and the
    caching half is what makes a later `capture_logs()` see nothing.

    fix(#1064 codex r4): `configured_logging()` replaces a fixture that only
    saved and restored. Restoring was never sufficient on its own — while
    caching is on, any module-level proxy emitting inside the window freezes
    permanently, and a proxy-local bind survives every restore. The helper
    disables caching after `setup_logging()`, which is the only order that
    works, and this file was one `logger.info` away from being the test that
    demonstrated it.

    It stays a context manager in the body rather than a fixture: pytest swaps
    `sys.stdout`/`stderr` for the call phase only, so a handler created during
    fixture setup binds to a stream capsys is not capturing.
    """
    with configured_logging(log_level="INFO"):
        logger = structlog.stdlib.get_logger("test.redaction")
        logger.info(
            "auth_attempt", token="my-supersecret-jwt-token-value", user_id="alice"
        )

        captured = capsys.readouterr()
        out = captured.out + captured.err  # destination depends on handler config

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
