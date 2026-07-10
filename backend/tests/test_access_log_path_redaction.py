"""Access-log paths must not persist bearer capability values."""

import pytest

from app.api.middleware.logging import safe_access_log_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/maps/shared/SYNTHETIC_SENTINEL", "/maps/shared/[REDACTED]"),
        (
            "/maps/shared/SYNTHETIC_SENTINEL/card",
            "/maps/shared/[REDACTED]/card",
        ),
        (
            "/api/maps/shared/SYNTHETIC_SENTINEL/card",
            "/api/maps/shared/[REDACTED]/card",
        ),
        ("/maps/ordinary-map-id", "/maps/ordinary-map-id"),
        ("/maps/shared", "/maps/shared"),
    ],
)
def test_safe_access_log_path(path: str, expected: str) -> None:
    logged_path = safe_access_log_path(path)

    assert logged_path == expected
    assert "SYNTHETIC_SENTINEL" not in logged_path
