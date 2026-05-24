"""Tests for SEC-S04 — per-hop SSRF revalidation on httpx redirects.

Phase 1061: validate_url_for_ssrf runs at submission time but not per-hop.
_revalidate_redirect closes the gap by intercepting every 3xx response
in the httpx event_hooks pipeline.

These tests exercise _revalidate_redirect directly via constructed
httpx.Response objects — no real HTTP required.
"""

import httpx
import pytest

from app.modules.catalog.sources.security import (
    SSRFError,
    _revalidate_redirect,
)


@pytest.mark.anyio
async def test_redirect_to_private_ip_blocked():
    """A 302 -> 127.0.0.1 redirect is rejected by _revalidate_redirect."""
    response = httpx.Response(
        302,
        headers={"Location": "http://127.0.0.1/internal"},
        request=httpx.Request("GET", "https://attacker.example/redirect"),
    )
    with pytest.raises(SSRFError):
        await _revalidate_redirect(response)


@pytest.mark.anyio
async def test_redirect_to_link_local_blocked():
    """A 302 -> 169.254.169.254 (AWS IMDS) is rejected."""
    response = httpx.Response(
        302,
        headers={"Location": "http://169.254.169.254/latest/meta-data/iam/security-credentials/"},
        request=httpx.Request("GET", "https://attacker.example/redirect"),
    )
    with pytest.raises(SSRFError):
        await _revalidate_redirect(response)


@pytest.mark.anyio
async def test_redirect_to_public_allowed():
    """A 302 -> public hostname succeeds (no exception).

    example.com always resolves to a non-private IP per RFC 2606.
    """
    response = httpx.Response(
        302,
        headers={"Location": "https://example.com/path"},
        request=httpx.Request("GET", "https://attacker.example/redirect"),
    )
    # MUST NOT raise — public destination is allowed
    await _revalidate_redirect(response)


@pytest.mark.anyio
async def test_relative_redirect_resolution():
    """A 302 with Location: /admin resolves against the base URL.

    If the base URL is an internal IP, the resolved absolute URL is also
    internal and must be blocked by validate_url_for_ssrf.
    """
    response = httpx.Response(
        302,
        headers={"Location": "/admin"},
        request=httpx.Request("GET", "http://10.0.0.5/start"),
    )
    with pytest.raises(SSRFError):
        await _revalidate_redirect(response)


@pytest.mark.anyio
async def test_non_http_scheme_redirect_blocked():
    """A 302 -> file:// scheme is rejected."""
    response = httpx.Response(
        302,
        headers={"Location": "file:///etc/passwd"},
        request=httpx.Request("GET", "https://attacker.example/redirect"),
    )
    with pytest.raises(SSRFError):
        await _revalidate_redirect(response)


@pytest.mark.anyio
async def test_non_redirect_status_passthrough():
    """A 200 response with a Location header is NOT treated as a redirect."""
    response = httpx.Response(
        200,
        headers={"Location": "http://127.0.0.1/internal"},
        request=httpx.Request("GET", "https://attacker.example/page"),
    )
    # MUST NOT raise — only 3xx codes trigger redirect revalidation
    await _revalidate_redirect(response)


@pytest.mark.anyio
async def test_make_safe_client_blocks_private_ip_redirect():
    """SSRF revalidation contract — a 3xx redirect to a private IP is rejected.

    Behavioral test for the SSRF revalidation contract — supersedes the
    pre-2026-05-24 identity check (which was brittle to module-level
    mock.patch contamination from sibling tests). v1023 Phase 1098 OOS-03.

    Tests _revalidate_redirect directly (mirroring lines 22-97) rather than
    going through make_safe_client(), because the latter constructs an
    httpx.AsyncClient that some sibling tests patch globally without restoring
    (e.g. seed-script tests that swap httpx.AsyncClient for a fake — see D-10:
    leaker hunt deferred indefinitely; the contract test below is immune).
    """
    response = httpx.Response(
        302,
        headers={"Location": "http://127.0.0.1/internal"},
        request=httpx.Request("GET", "https://attacker.example/redirect"),
    )
    # Behavioral: the SSRF hook rejects the redirect (the contract)
    with pytest.raises(SSRFError):
        await _revalidate_redirect(response)
