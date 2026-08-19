"""Tests for branding settings API endpoints."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_get_branding_default(client: AsyncClient):
    """GET /api/settings/branding/ returns show_badge=true and no privacy_url by default (no auth)."""
    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"show_badge": True, "privacy_url": None}


@pytest.mark.anyio
async def test_get_branding_consults_extension(client: AsyncClient):
    """The route invokes BrandingExtension.get_branding_defaults() each call."""
    from app.platform.extensions.defaults import DefaultBrandingExtension

    with patch.object(
        DefaultBrandingExtension,
        "get_branding_defaults",
        return_value={"show_badge": True},
    ) as spy:
        resp = await client.get("/api/settings/branding/")
        assert resp.status_code == 200
        spy.assert_called()


@pytest.mark.anyio
async def test_put_branding_returns_404_community(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /api/settings/branding/ returns 405 in community mode (no PUT route)."""
    resp = await client.put(
        "/api/settings/branding/",
        json={"show_badge": False},
        headers=admin_auth_header,
    )
    assert resp.status_code == 405


@pytest.mark.anyio
async def test_put_branding_invalid_body(client: AsyncClient, admin_auth_header: dict):
    """PUT /api/settings/branding/ with invalid body returns 405.

    Note: In community mode, no PUT route exists (enterprise only).
    """
    resp = await client.put(
        "/api/settings/branding/",
        json={"wrong_key": "value"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 405


@pytest.mark.anyio
async def test_put_branding_key_returns_404_in_community(
    client: AsyncClient, admin_auth_header: dict
):
    """PUT /api/settings/ for an enterprise-only branding key returns 404, not 403.

    404 (with no detail body) prevents trivial enumeration of paid keys —
    consistent with the require_enterprise() guard contract.
    """
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"branding.show_badge": False}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404
    body = resp.json()
    detail = str(body.get("detail", "")).lower()
    for word in ("enterprise", "upgrade", "feature"):
        assert word not in detail, f"Gate response leaked '{word}'"


@pytest.mark.anyio
async def test_reset_branding_key_returns_404_in_community(
    client: AsyncClient, admin_auth_header: dict
):
    """POST /api/settings/reset/ for an enterprise-only branding key returns 404."""
    resp = await client.post(
        "/api/settings/reset/",
        json={"keys": ["branding.show_badge"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_branding_after_config_override(client: AsyncClient):
    """GET /api/settings/branding/ returns correct value after PersistentConfig.set()."""
    from app.core.dependencies import get_db
    from app.api.main import app
    from app.core.persistent_config import BRANDING_SHOW_BADGE

    # Override via PersistentConfig directly (bypasses enterprise gate)
    get_db_override = app.dependency_overrides.get(get_db)
    assert get_db_override is not None

    async for db in get_db_override():
        await BRANDING_SHOW_BADGE.set(db, False)

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"show_badge": False, "privacy_url": None}

    # Restore default
    async for db in get_db_override():
        await BRANDING_SHOW_BADGE.set(db, True)


@pytest.mark.anyio
async def test_get_branding_privacy_url_unset_by_default(
    client: AsyncClient, admin_auth_header: dict
):
    """PRIV-1: no privacy_url is configured until an admin sets one.

    GET /api/settings/branding/ returns null (community and self-hosted
    instances never link to another operator's privacy page by default), and
    PUT /api/settings/ with a configured URL makes it appear.
    """
    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] is None

    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": "https://operator.example.com/privacy"}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] == "https://operator.example.com/privacy"

    # Clearing it back to empty restores the "no link shown" default.
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": ""}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] is None


@pytest.mark.anyio
async def test_put_privacy_url_null_clears_it(
    client: AsyncClient, admin_auth_header: dict
):
    """JSON null is a legitimate clear, same as "" -- distinct from a falsy
    non-string (False, 0, [], {}), which must 422 instead.
    """
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": "https://operator.example.com/privacy"}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": None}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] is None


@pytest.mark.parametrize(
    "value",
    [False, 0, [], {}],
)
@pytest.mark.anyio
async def test_put_privacy_url_rejects_falsy_non_strings(
    client: AsyncClient, admin_auth_header: dict, value
):
    """A falsy non-string value (False, 0, [], {}) is a type error, not a
    clear -- only JSON null and an empty/whitespace string clear the link.
    `if not v` would have caught these too and cleared silently instead of
    422ing, since every one of them is falsy in Python.
    """
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": value}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "value",
    [
        "not-a-url",
        "javascript:alert(1)",
        "data:text/html,x",
        "//evil.example.com/p",
        "https://example.com:not-a-port/x",
        "https://:443/x",
        "https://exa mple.com/x",
        "https://exam_ple.com/x",
        "https://-bad.com/x",
        "https://999.999.999.999/x",
        "https://1.2.3.4.5/x",
        "https://192.168.1/x",
        "https://0x7f.1/x",
        "https://a..b/x",
        "https://́.example.com/x",
        "https://xn--a.com/x",
        "https://xn--.com/x",
        "https://[v1.foo]/x",
        "https://[fe80::1%25eth0]/x",
        "https://[fe80::1%eth0]/x",
        "https://[1.2.3.4]/x",
        "https://xn--lsa.example/x",
        "https://﹇.com/x",
        "https://192.168.1./x",
        "https://999.999.999.999./x",
        "https://999。999。999。999/x",
        "https://192.168.1。/x",
    ],
)
@pytest.mark.anyio
async def test_put_privacy_url_rejects_non_url(
    client: AsyncClient, admin_auth_header: dict, value: str
):
    """PUT /api/settings/ rejects a privacy_url that is not a safe absolute http(s) URL.

    Covers the XSS-relevant shapes, not just "not a URL": a javascript:/data:
    URI or a scheme-relative value would otherwise reach the login page as a
    raw <a href>. Also covers a malformed authority a browser cannot resolve
    (a non-numeric port, a netloc with no real hostname, an embedded space, an
    underscore, or a leading hyphen) -- urlsplit leaves that junk sitting in
    netloc/hostname rather than rejecting it outright, so the scheme/netloc
    check alone would let it through. And a numeric-last-label host a
    browser reads as an attempted IPv4 address: out of range
    (999.999.999.999), too many parts (1.2.3.4.5), or a legacy short form a
    browser silently expands to a different address (192.168.1, 0x7f.1) --
    the per-label characters alone look like a valid DNS name, so a check
    that stopped at character class would accept all four. Also covers an
    empty label (a..b), a label that is only a Unicode combining mark, and a
    label already spelled as "xn--" A-label punycode that does not decode to
    a real IDN label -- fail-closed even though Chromium/WebKit accept any
    ASCII "xn--" label unvalidated, since Firefox does not. And a bracketed
    authority that is not a plain, unscoped IPv6 literal: an IPvFuture
    literal no browser implements ([v1.foo]), an IPv4 literal (invalid in
    brackets, [1.2.3.4]), and a scoped IPv6 zone ID whether or not its "%"
    is percent-escaped ([fe80::1%eth0], [fe80::1%25eth0]) -- each would
    otherwise fall through to the DNS-name or numeric-last-label case once
    `.hostname` strips the brackets. And "xn--lsa" (the punycode spelling
    of a bare combining mark): U-labels and decoded A-labels share one
    rule set, so the encoded form of an already-rejected host cannot slip
    through in its "xn--..." spelling. And U+FE47 -- hostname validity is
    now the `idna` package's UTS46 ToASCII, which maps this presentation
    variant to "[" per the UTS46 mapping table and then rejects the
    result, the same as a literal "[" would be (STD3 disallows it outside
    the bracketed-authority syntax `urlsplit` already stripped away). And a
    numeric-last-label host with a single trailing DNS root dot: the dot
    makes `hostname.rsplit(".", 1)[-1]` return an empty string, which is
    neither a digit nor "0x"-prefixed, so the ends-in-a-number check was
    skipped entirely and idna.encode() (DNS label SYNTAX only, no IPv4
    opinion) accepted "999" and "1" as ordinary-looking labels. And the same
    numeric-last-label host spelled with ideographic full stops (U+3002,
    "。" instead of ".") instead of a root dot: the raw string has no ASCII
    "." at all, so it looked like one giant label with no numeric tail --
    only visible as ends-in-a-number AFTER UTS46 maps "。" to ".", which is
    why that mapping now runs before this check, not after.
    """
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": value}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_put_privacy_url_accepts_query_and_fragment(
    client: AsyncClient, admin_auth_header: dict
):
    """A real operator policy URL (Google Docs, Notion, SharePoint) often
    carries a query string or a fragment; the privacy_url validator must not
    strip or reject either, unlike the public_app_url/public_api_url shape
    rule it deliberately does not share.
    """
    value = "https://docs.google.com/document/d/abc123/edit?usp=sharing#heading=h.xyz"
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": value}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] == value

    # Restore default so this test does not leak state to others.
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": ""}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "value",
    [
        "https://[::1]/x",
        "https://10.0.0.1:8443/x",
        "https://[2001:db8::1]:8443/x",
    ],
)
@pytest.mark.anyio
async def test_put_privacy_url_accepts_ip_literal_hosts(
    client: AsyncClient, admin_auth_header: dict, value: str
):
    """An IP-literal host (IPv6 or IPv4, with or without an explicit port) is
    a legitimate privacy_url target, not just a DNS name -- the hostname
    allowlist accepts both forms via ipaddress.ip_address(), same as the
    rejection cases above prove it rejects a malformed one.
    """
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": value}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] == value

    # Restore default so this test does not leak state to others.
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": ""}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "value",
    [
        "https://例え.テスト/privacy",
        "https://xn--r8jz45g.xn--zckzah/privacy",
    ],
)
@pytest.mark.anyio
async def test_put_privacy_url_accepts_internationalized_hosts(
    client: AsyncClient, admin_auth_header: dict, value: str
):
    """A browser-valid internationalized host, in either its native Unicode
    spelling or its already-punycode "xn--" form, is a legitimate
    privacy_url target. Round-trips unchanged: the operator's URL is stored
    and served exactly as entered, not rewritten to a canonical form,
    matching what a browser does with the same input.
    """
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": value}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] == value

    # Restore default so this test does not leak state to others.
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": ""}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "value",
    [
        "https://10.0.0.1./x",
        "https://example.com./x",
        "https://１２７.０.０.１/x",
        "https://例え。テスト/x",
    ],
)
@pytest.mark.anyio
async def test_put_privacy_url_accepts_uts46_mapped_hosts(
    client: AsyncClient, admin_auth_header: dict, value: str
):
    """Browser-valid hosts that only pass because UTS46 mapping runs before
    every other check, stored exactly as entered (never rewritten to a
    canonical or mapped form). A single trailing DNS root dot: on a
    canonical IPv4 host (legal but pointless) and on an ordinary DNS name
    (the common, meaningful case) alike. A fullwidth-digit IPv4 host
    ("１２７.０.０.１", which UTS46 maps to "127.0.0.1"). An internationalized
    DNS name written with ideographic full stops instead of ASCII dots
    ("例え。テスト", which a browser reads identically to "例え.テスト").
    """
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": value}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] == value

    # Restore default so this test does not leak state to others.
    resp = await client.put(
        "/api/settings/",
        json={"settings": {"privacy_url": ""}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_get_branding_drops_an_unsafe_stored_privacy_url(client: AsyncClient):
    """PRIV-1 reader-side defense: an unsafe stored value must never reach
    the login page as a raw <a href>, even if it bypassed the admin-write
    validator — a row written before that check existed, or by any other
    path than PUT /api/settings/. Writes through PersistentConfig.set()
    directly, which (like a raw DB row) has no shape opinion on a str value;
    only the read path in router_public.py is under test here.
    """
    from app.core.dependencies import get_db
    from app.api.main import app
    from app.core.persistent_config import PRIVACY_URL

    get_db_override = app.dependency_overrides.get(get_db)
    assert get_db_override is not None

    async for db in get_db_override():
        await PRIVACY_URL.set(db, "javascript:alert(document.cookie)")

    resp = await client.get("/api/settings/branding/")
    assert resp.status_code == 200
    assert resp.json()["privacy_url"] is None

    # Restore default
    async for db in get_db_override():
        await PRIVACY_URL.set(db, "")
