"""SEC-15: .env.example admin/admin defaults replaced with required-empty.

Pins the v13.13 closure of M-69 (paired with H-28 JWT_SECRET_KEY pattern).
Operators who copy .env.example to .env without changes get a clear boot
failure ("required environment variables not set"), not a silent
admin/admin foothold.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


@pytest.fixture(scope="module")
def env_example_text() -> str:
    return ENV_EXAMPLE.read_text()


def test_admin_username_is_empty(env_example_text):
    """GEOLENS_ADMIN_USERNAME line MUST end in '=' with no value."""
    lines = [
        line
        for line in env_example_text.splitlines()
        if line.startswith("GEOLENS_ADMIN_USERNAME=")
    ]
    assert len(lines) == 1, (
        f"expected exactly 1 GEOLENS_ADMIN_USERNAME line, got {len(lines)}"
    )
    line = lines[0]
    # The whole line is exactly "GEOLENS_ADMIN_USERNAME="
    assert line.strip() == "GEOLENS_ADMIN_USERNAME=", (
        f"SEC-15: GEOLENS_ADMIN_USERNAME must have an empty value (line ends with '='); "
        f"got: {line!r}"
    )


def test_admin_password_is_empty(env_example_text):
    """GEOLENS_ADMIN_PASSWORD line MUST end in '=' with no value."""
    lines = [
        line
        for line in env_example_text.splitlines()
        if line.startswith("GEOLENS_ADMIN_PASSWORD=")
    ]
    assert len(lines) == 1
    assert lines[0].strip() == "GEOLENS_ADMIN_PASSWORD=", (
        f"SEC-15: GEOLENS_ADMIN_PASSWORD must have an empty value; got: {lines[0]!r}"
    )


def test_admin_block_has_required_marker(env_example_text):
    """Comment block above admin block uses the [REQUIRED] convention from JWT_SECRET_KEY."""
    # The comment block immediately above GEOLENS_ADMIN_USERNAME= MUST contain "[REQUIRED]"
    lines = env_example_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("GEOLENS_ADMIN_USERNAME="):
            # Look at the 4 lines above for "[REQUIRED]"
            preceding = "\n".join(lines[max(0, i - 4):i])
            assert "[REQUIRED]" in preceding, (
                f"SEC-15: comment block above GEOLENS_ADMIN_USERNAME must contain "
                f"'[REQUIRED]' marker. Preceding 4 lines:\n{preceding}"
            )
            return
    pytest.fail("Did not find GEOLENS_ADMIN_USERNAME= line at all")


def test_admin_password_block_has_required_marker(env_example_text):
    """Comment block above GEOLENS_ADMIN_PASSWORD also uses [REQUIRED] (boot-fail safety)."""
    lines = env_example_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("GEOLENS_ADMIN_PASSWORD="):
            preceding = "\n".join(lines[max(0, i - 4):i])
            assert "[REQUIRED]" in preceding, (
                f"SEC-15: comment block above GEOLENS_ADMIN_PASSWORD must contain "
                f"'[REQUIRED]' marker. Preceding 4 lines:\n{preceding}"
            )
            return
    pytest.fail("Did not find GEOLENS_ADMIN_PASSWORD= line at all")


def test_jwt_secret_key_pattern_preserved(env_example_text):
    """Regression: the existing JWT_SECRET_KEY required-empty line is unchanged (H-28 from Phase 268)."""
    lines = [
        line
        for line in env_example_text.splitlines()
        if line.startswith("JWT_SECRET_KEY=")
    ]
    assert len(lines) == 1
    assert lines[0].strip() == "JWT_SECRET_KEY=", (
        f"H-28 regression: JWT_SECRET_KEY required-empty was modified; "
        f"got: {lines[0]!r}"
    )
