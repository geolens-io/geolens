"""SEC-05: _request_origin validates derived origin against CORS allowlist.

Pins the v13.13 closure of M-67. When CORS_ALLOWED_ORIGINS is set, an
attacker who steers X-Forwarded-Host or Origin to a non-allowlisted host
gets None back — falling through to the configured public_app_url /
public_api_url or default, NOT the attacker-controlled value.
"""

from types import SimpleNamespace
from unittest.mock import patch

from app.core.public_urls import (
    _DEFAULT_PUBLIC_API_URL,
    _DEFAULT_PUBLIC_APP_URL,
    _request_origin,
    _request_origin_decision,
    resolve_public_api_url,
    resolve_public_app_url,
)


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


# ---------------------------------------------------------------------------
# fix(#1778): codebase audit 2026-08-30, "SEC-05's CORS-allowlist gate on
# request-derived origins is bypassed two lines later by a raw Host fallback".
#
# _request_origin returning None was read by both resolvers as "no origin to
# derive", so they fell through to request.url.netloc -- Starlette's read of
# the Host header, which frontend/nginx.conf forwards verbatim from the client
# with no server_name restriction. The allowlist decided which of two code
# paths ran; both returned the attacker's host.
#
# Counterfactual: drop `and not allowlist_rejected` from either resolver and
# the matching test below returns https://attacker.example instead of the
# default.
# ---------------------------------------------------------------------------


def test_decision_distinguishes_rejection_from_absence():
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = ["https://app.example.com"]
        rejected = _mock_request({"origin": "https://attacker.example"})
        assert _request_origin_decision(rejected) == (None, True)

        # No headers to derive anything from: absence, not rejection.
        absent = _mock_request({}, netloc="")
        assert _request_origin_decision(absent) == (None, False)

        assert _request_origin_decision(None) == (None, False)


def test_api_url_does_not_fall_back_to_a_rejected_host():
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = ["https://app.example.com"]
        mock_settings.env_only_config = False
        req = _mock_request(
            {"host": "attacker.example"},
            scheme="https",
            netloc="attacker.example",
        )
        assert (
            resolve_public_api_url(None, None, None, request=req)
            == _DEFAULT_PUBLIC_API_URL
        )


def test_app_url_does_not_fall_back_to_a_rejected_host():
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = ["https://app.example.com"]
        mock_settings.env_only_config = False
        req = _mock_request(
            {"host": "attacker.example"},
            scheme="https",
            netloc="attacker.example",
        )
        assert (
            resolve_public_app_url(None, None, None, request=req)
            == _DEFAULT_PUBLIC_APP_URL
        )


def test_an_allowlisted_host_still_resolves():
    """The gate must refuse the rejection, not every request-derived origin."""
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = ["https://app.example.com"]
        mock_settings.env_only_config = False
        req = _mock_request(
            {"host": "app.example.com", "x-forwarded-proto": "https"},
            scheme="https",
            netloc="app.example.com",
        )
        assert (
            resolve_public_app_url(None, None, None, request=req)
            == "https://app.example.com"
        )


def test_unconfigured_allowlist_keeps_the_dev_host_fallback():
    """With CORS_ALLOWED_ORIGINS empty nothing is rejected, so the fallback that
    makes a no-config dev stack work is untouched."""
    with patch("app.core.public_urls.settings") as mock_settings:
        mock_settings.cors_origins_list = []
        mock_settings.env_only_config = False
        req = _mock_request({}, scheme="http", netloc="localhost:8000")
        assert (
            resolve_public_app_url(None, None, None, request=req)
            == "http://localhost:8000"
        )
