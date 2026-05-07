"""SEC-05: _request_origin validates derived origin against CORS allowlist.

Pins the v13.13 closure of M-67. When CORS_ALLOWED_ORIGINS is set, an
attacker who steers X-Forwarded-Host or Origin to a non-allowlisted host
gets None back — falling through to the configured public_app_url /
public_api_url or default, NOT the attacker-controlled value.
"""

from types import SimpleNamespace
from unittest.mock import patch

from app.core.public_urls import _request_origin


def _mock_request(
    headers: dict,
    *,
    scheme: str = "http",
    netloc: str = "localhost:8000",
    root_path: str = "",
):
    """Build a minimal mock Request with the given headers and url scheme/host."""
    return SimpleNamespace(
        headers=headers,
        url=SimpleNamespace(scheme=scheme, netloc=netloc),
        scope={"root_path": root_path},
    )


def test_no_cors_config_returns_request_origin():
    """With CORS_ALLOWED_ORIGINS empty (dev mode), origin is returned unchanged."""
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = []
        req = _mock_request({"origin": "http://localhost:5173"})
        assert _request_origin(req) == "http://localhost:5173"


def test_origin_in_allowlist_returns_origin():
    """With CORS_ALLOWED_ORIGINS set, an origin in the list is returned."""
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = ["https://app.example.com"]
        req = _mock_request({"origin": "https://app.example.com"})
        assert _request_origin(req) == "https://app.example.com"


def test_origin_not_in_allowlist_returns_none():
    """An attacker-set Origin: https://attacker.com is rejected by the allowlist."""
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = ["https://app.example.com"]
        req = _mock_request({"origin": "https://attacker.com"})
        assert _request_origin(req) is None


def test_xforwarded_host_attack_blocked():
    """When Origin is absent, X-Forwarded-Host: attacker.com is rejected."""
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = ["https://app.example.com"]
        req = _mock_request(
            {
                "x-forwarded-proto": "https",
                "x-forwarded-host": "attacker.com",
            },
            scheme="https",
            netloc="attacker.com",
        )
        assert _request_origin(req) is None


def test_origin_normalization_case_and_trailing_slash():
    """Allowlist comparison is case-insensitive and trailing-slash-tolerant."""
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = ["https://app.example.com/"]
        req = _mock_request({"origin": "HTTPS://APP.EXAMPLE.COM"})
        # normalize_public_url strips trailing slash; lower() handles case
        result = _request_origin(req)
        assert result is not None
        assert result.lower() == "https://app.example.com"


def test_referer_resolves_to_host_only():
    """Referer: https://app.example.com/foo/bar resolves to the host portion only."""
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = ["https://app.example.com"]
        req = _mock_request({"referer": "https://app.example.com/foo/bar"})
        assert _request_origin(req) == "https://app.example.com"


def test_referer_to_attacker_blocked():
    """Referer: https://attacker.com/... is rejected."""
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = ["https://app.example.com"]
        req = _mock_request({"referer": "https://attacker.com/login"})
        assert _request_origin(req) is None


def test_no_request_returns_none():
    """request=None returns None unchanged — pre-existing behavior preserved."""
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = ["https://app.example.com"]
        assert _request_origin(None) is None
