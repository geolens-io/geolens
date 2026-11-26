"""Regression: per-token frame-ancestors on the /m/{token}
embed HTML shell.

Domain restrictions previously protected only the tile/data calls, not the
embeddable HTML document, so any site could frame the shell. The fix serves the
shell's framing policy through a validated edge route:

  * Backend: ``GET /embed/frame-policy?token=...`` validates the token and emits
    a token-specific ``Content-Security-Policy`` + ``X-Embed-Frame-Ancestors``.
  * Edge (nginx): an ``auth_request`` to that endpoint copies the directive onto
    the static HTML response via ``auth_request_set``; X-Frame-Options stays
    omitted ONLY for /m/* while normal SPA routes keep SAMEORIGIN.

These tests assert the backend response headers (allowed domain, denied domain,
unrestricted Community embed, invalid token) plus the nginx wiring invariants.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.maps.models import Map
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.public_router import embed_token_from_query

from tests.factories import get_user_id
from tests.repo_paths import repo_root


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_public_map(session: AsyncSession, *, created_by: uuid.UUID) -> Map:
    map_obj = Map(
        name=f"Frame Policy Map {uuid.uuid4().hex[:6]}",
        description="builder-audit #338 P0-02 frame policy test",
        visibility="public",
        created_by=created_by,
    )
    session.add(map_obj)
    await session.flush()
    await session.refresh(map_obj)
    return map_obj


async def _create_embed_token(
    session: AsyncSession,
    *,
    map_id: uuid.UUID,
    created_by: uuid.UUID,
    allowed_origins: list[str] | None = None,
    is_active: bool = True,
    expires_days: int = 30,
) -> str:
    """Insert an EmbedToken and return the raw (unhashed) token string."""
    raw = "et_" + secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)
    token_obj = EmbedToken(
        map_id=map_id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        token_hint="et_..." + raw[-8:],
        scoped_dataset_ids=[],
        expires_at=expires_at,
        is_active=is_active,
        created_by=created_by,
        allowed_origins=allowed_origins,
    )
    session.add(token_obj)
    await session.flush()
    return raw


# ---------------------------------------------------------------------------
# Backend endpoint header behavior
# ---------------------------------------------------------------------------


async def test_frame_policy_domain_locked_token_restricts_frame_ancestors(
    client: AsyncClient, test_db_session: AsyncSession
):
    """A domain-locked token returns frame-ancestors with 'self' + the allowed
    origins, and EXCLUDES any non-allowlisted (denied) origin."""
    uid = await get_user_id(test_db_session, "admin")
    map_obj = await _create_public_map(test_db_session, created_by=uid)
    raw = await _create_embed_token(
        test_db_session,
        map_id=map_obj.id,
        created_by=uid,
        allowed_origins=["https://partner.example"],
    )
    await test_db_session.commit()

    resp = await client.get("/embed/frame-policy", params={"token": raw})
    assert resp.status_code == 200
    csp = resp.headers.get("content-security-policy", "")
    fa = resp.headers.get("x-embed-frame-ancestors", "")
    assert "frame-ancestors 'self' https://partner.example" in csp, (
        f"Allowed origin must appear in frame-ancestors, got: {csp!r}"
    )
    assert "frame-ancestors 'self' https://partner.example" == fa, (
        f"X-Embed-Frame-Ancestors must carry just the directive, got: {fa!r}"
    )
    # A denied origin (never configured) must NOT be present in the policy.
    assert "https://evil.example" not in csp, (
        f"Denied origin must not appear in frame-ancestors, got: {csp!r}"
    )
    assert "*" not in csp, f"frame-ancestors must never contain '*', got: {csp!r}"


async def test_frame_policy_unrestricted_token_is_open_framing(
    client: AsyncClient, test_db_session: AsyncSession
):
    """An unrestricted (Community) token with no allowed_origins emits an
    explicit open-framing policy: no frame-ancestors directive, no
    X-Frame-Options, and never frame-ancestors '*'."""
    uid = await get_user_id(test_db_session, "admin")
    map_obj = await _create_public_map(test_db_session, created_by=uid)
    raw = await _create_embed_token(
        test_db_session,
        map_id=map_obj.id,
        created_by=uid,
        allowed_origins=None,
    )
    await test_db_session.commit()

    resp = await client.get("/embed/frame-policy", params={"token": raw})
    assert resp.status_code == 200
    csp = resp.headers.get("content-security-policy", "")
    assert resp.headers.get("x-embed-frame-ancestors", "") == "", (
        "Unrestricted token must emit an EMPTY frame-ancestors directive (open framing)."
    )
    assert "frame-ancestors" not in csp, (
        f"Unrestricted Community embed must stay frameable (no directive), got: {csp!r}"
    )
    assert "*" not in csp, (
        f"Open framing must not use frame-ancestors '*', got: {csp!r}"
    )
    # The validated embed route owns its CSP, so X-Frame-Options is omitted.
    assert "x-frame-options" not in resp.headers, (
        "X-Frame-Options must be omitted for the validated embed route."
    )


async def test_frame_policy_invalid_token_fails_closed_none(
    client: AsyncClient, test_db_session: AsyncSession
):
    """An unknown / revoked / expired token fails closed with
    frame-ancestors 'none' so the shell cannot be framed anywhere."""
    uid = await get_user_id(test_db_session, "admin")
    map_obj = await _create_public_map(test_db_session, created_by=uid)
    # Revoked token — present in DB but is_active=False.
    raw = await _create_embed_token(
        test_db_session,
        map_id=map_obj.id,
        created_by=uid,
        allowed_origins=["https://partner.example"],
        is_active=False,
    )
    await test_db_session.commit()

    resp = await client.get("/embed/frame-policy", params={"token": raw})
    assert resp.status_code == 200
    csp = resp.headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp, (
        f"Revoked token must fail closed with frame-ancestors 'none', got: {csp!r}"
    )
    assert resp.headers.get("x-embed-frame-ancestors", "") == "frame-ancestors 'none'"


async def test_frame_policy_unknown_token_fails_closed_none(
    client: AsyncClient, test_db_session: AsyncSession
):
    """A completely unknown token string fails closed with 'none'."""
    resp = await client.get(
        "/embed/frame-policy", params={"token": "et_does_not_exist"}
    )
    assert resp.status_code == 200
    csp = resp.headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp, (
        f"Unknown token must fail closed with frame-ancestors 'none', got: {csp!r}"
    )


async def test_frame_policy_empty_token_is_open_framing(client: AsyncClient):
    """Codex P1 (#338): a plain /m/<shareToken> view sends NO embed token (empty
    `et`), which must yield OPEN framing — not the old fail-closed 'none' that
    broke every normal shared-map iframe. Fail-closed is reserved for a PRESENT
    but invalid/revoked token; private data stays protected at the tile layer."""
    resp = await client.get("/embed/frame-policy", params={"token": ""})
    assert resp.status_code == 200
    csp = resp.headers.get("content-security-policy", "")
    assert resp.headers.get("x-embed-frame-ancestors", "") == "", (
        "No embed token must emit an EMPTY frame-ancestors directive (open framing)."
    )
    assert "frame-ancestors" not in csp, (
        f"A plain share (no et) must not restrict framing, got: {csp!r}"
    )


# ---------------------------------------------------------------------------
# The shell's query string, as the edge forwards it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("embed=true&et=tok", "tok"),
        ("embed=true&%65t=tok", "tok"),
        ("embed=true&et=a%2Bb+c", "a+b c"),
        ("embed=true", ""),
        ("", ""),
        ("embed=true&et=", ""),
        ("embed=true&et", ""),
        ("embed=true;et=tok", ""),
        ("embed=true&e+t=tok", ""),
        ("embed=true&ET=&et=tok", None),
        ("embed=true&eT=tok", None),
        ("embed=true&%45%54=tok&et=tok", None),
        ("embed=true&et=tok&et=", None),
        ("embed=true&et=&et=tok", None),
        ("&".join(["x=1"] * 300) + "&et=tok", None),
    ],
)
def test_embed_token_from_query_matches_the_viewer_page(query, expected):
    """The policy reads `et` as URLSearchParams.get does, or None when ambiguous."""
    assert embed_token_from_query(query) == expected


async def _locked_token(test_db_session: AsyncSession) -> str:
    uid = await get_user_id(test_db_session, "admin")
    map_obj = await _create_public_map(test_db_session, created_by=uid)
    raw = await _create_embed_token(
        test_db_session,
        map_id=map_obj.id,
        created_by=uid,
        allowed_origins=["https://partner.example"],
    )
    await test_db_session.commit()
    return raw


async def test_frame_policy_reads_encoded_et_name_from_shell_query(
    client: AsyncClient, test_db_session: AsyncSession
):
    """A percent-encoded `et` name still gets the locked token's policy."""
    raw = await _locked_token(test_db_session)
    # The edge's raw $arg_et does not match `%65t`, so it sends an empty token.
    resp = await client.get(
        "/embed/frame-policy",
        params={"token": ""},
        headers={"X-Embed-Query": f"embed=true&%65t={raw}"},
    )
    assert resp.status_code == 200
    assert (
        resp.headers["x-embed-frame-ancestors"]
        == "frame-ancestors 'self' https://partner.example"
    )


@pytest.mark.parametrize(
    ("shell_query", "edge_token"),
    [
        ("embed=true&ET=&et={raw}", ""),
        ("embed=true&et={raw}&et=", "{raw}"),
        ("embed=true&et=&et={raw}", ""),
    ],
)
async def test_frame_policy_ambiguous_et_fails_closed(
    client: AsyncClient, test_db_session: AsyncSession, shell_query, edge_token
):
    """A duplicate or case-variant `et` gets frame-ancestors 'none'."""
    raw = await _locked_token(test_db_session)
    resp = await client.get(
        "/embed/frame-policy",
        params={"token": edge_token.format(raw=raw)},
        headers={"X-Embed-Query": shell_query.format(raw=raw)},
    )
    assert resp.status_code == 200
    assert resp.headers["x-embed-frame-ancestors"] == "frame-ancestors 'none'"
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]


async def test_frame_policy_shell_query_without_et_is_open_framing(
    client: AsyncClient,
):
    """A forwarded query with no `et` is a plain share: open framing."""
    resp = await client.get(
        "/embed/frame-policy",
        params={"token": ""},
        headers={"X-Embed-Query": "embed=true&zoom=4"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("x-embed-frame-ancestors", "") == ""
    assert "frame-ancestors" not in resp.headers.get("content-security-policy", "")


# ---------------------------------------------------------------------------
# Edge (nginx) wiring invariants — config-presence assertions
# ---------------------------------------------------------------------------


def _nginx_conf_text() -> str:
    path = repo_root(__file__) / "frontend" / "nginx.conf"
    assert path.exists(), f"nginx.conf not found at {path}"
    return path.read_text()


def test_nginx_m_route_uses_frame_policy_auth_request():
    """The /m/ location must validate the token via auth_request and copy the
    per-token frame-ancestors into the CSP, with X-Frame-Options omitted."""
    conf = _nginx_conf_text()
    assert "auth_request /_embed_frame_policy;" in conf, (
        "P0-02: /m/ location must auth_request the embed frame-policy endpoint."
    )
    assert (
        "auth_request_set $embed_frame_ancestors $upstream_http_x_embed_frame_ancestors;"
        in conf
    ), "P0-02: the frame-ancestors directive must be copied from the API response."
    # The subrequest does not carry the parent query string, so the /m/
    # location captures it into `set` variables, which subrequests share.
    assert "set $embed_args $args;" in conf, (
        "the /m/ location must capture the whole query into $embed_args."
    )
    assert "proxy_set_header X-Embed-Query $embed_args;" in conf, (
        "the subrequest must forward the whole query, which the policy endpoint "
        "parses as the viewer page does; $arg_et reads `et` differently."
    )
    assert "/embed/frame-policy?token=$embed_et" in conf, (
        "the subrequest keeps sending `token` for an API without X-Embed-Query."
    )
    assert "${embed_frame_ancestors}" in conf, (
        "P0-02: the /m/ CSP must interpolate the per-token frame-ancestors value."
    )


def test_nginx_spa_route_keeps_sameorigin():
    """Normal SPA routes (location /) must keep X-Frame-Options: SAMEORIGIN and a
    frame-ancestors 'self' CSP — only /m/* relaxes framing."""
    conf = _nginx_conf_text()
    # The catch-all SPA location keeps the strict framing headers.
    assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in conf, (
        "P0-02: normal SPA routes must keep X-Frame-Options: SAMEORIGIN."
    )
    assert "frame-ancestors 'self'" in conf, (
        "P0-02: the SPA catch-all CSP must keep frame-ancestors 'self'."
    )


def test_nginx_m_route_serves_in_place_not_try_files():
    """The /m/ block must serve the SPA shell in place via `rewrite ... break`,
    NOT via `try_files $uri /index.html`. try_files internal-redirects to
    /index.html which re-enters `location /`, and nginx then emits location /'s
    add_header set — discarding this block's per-token frame-ancestors CSP and
    re-adding X-Frame-Options: SAMEORIGIN, which blocks every cross-origin embed.
    Regression guard for the 2026-07-21 fix (verified on the demo's live nginx)."""
    conf = _nginx_conf_text()
    start = conf.index("location ~ ^/m/ {")
    block = conf[start : conf.index("\n    }", start)]
    # Strip comment lines — the fix's own comment names `try_files` when
    # explaining the bug, so only inspect actual directives.
    directives = "\n".join(
        ln for ln in block.splitlines() if not ln.strip().startswith("#")
    )
    assert "rewrite ^ /index.html break;" in directives, (
        "the /m/ block must serve the SPA shell in place via `rewrite ... break`."
    )
    assert "try_files" not in directives, (
        "the /m/ block must NOT use try_files — its internal redirect to "
        "/index.html re-enters `location /` and discards the per-token embed headers."
    )
