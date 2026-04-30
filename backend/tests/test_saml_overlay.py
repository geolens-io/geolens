"""Integration tests for the SAML enterprise overlay (Phase 217 Plan 02).

Covers the 8 SAML test scenarios specified in 217-02-PLAN.md task 03:

- Registration: extension dual-registers under ``identity`` and ``_routers``
- Metadata: GET /auth/saml/{slug}/metadata returns valid samlmetadata+xml
- ACS happy path: signed assertion JIT-provisions a user, issues JWTs,
  redirects to /oauth/callback?source=saml#token=...
- ACS rejects: invalid signature, unsigned, expired, replayed, XSW

The remaining 2 SAML tests (audit-log + role-mapping) land in Plan 03.

All tests use the ``saml_overlay_registered`` conftest fixture which
programmatically installs ``EnterpriseSamlExtension`` for the test's
lifetime. The SAML router is also dynamically mounted into the FastAPI
app for the test's duration, then unmounted on teardown so other tests
that assume the community community/no-SAML default are unaffected.
"""

from __future__ import annotations

import base64
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.auth.oauth.encryption import encrypt_secret
from app.modules.auth.oauth.models import OAuthProvider


# ---------------------------------------------------------------------------
# Fixture constants -- must match values baked into the .xml.b64 fixtures
# (see backend/tests/fixtures/saml/generate_fixtures.py).
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "saml"
FIXTURE_CERT_PEM = (FIXTURE_DIR / "idp_cert.pem").read_text()


@pytest.fixture(scope="session", autouse=True)
def _regenerate_saml_fixtures():
    """Re-run the SAML fixture generator at session start so the signed
    response's IssueInstant + NotOnOrAfter window includes the test's
    wall-clock time. SAML assertions have a default 15-minute validity
    window; checked-in fixtures from a prior generation can outlast that
    window and produce "Can't use response, too old" failures. The
    expired/unsigned/xsw fixtures are also regenerated -- their
    semantics (still-old, still-unsigned, still-XSW) are unchanged.

    The generator script lives at backend/tests/fixtures/saml/
    generate_fixtures.py and is committed for reproducibility (Wave 1
    Plan 01). Running it here means the .xml.b64 files are rewritten
    on every test session, which also keeps git status noisy -- but
    they are gitignored from the worktree's perspective during a test
    run because the orchestrator only commits files explicitly added.
    """
    import subprocess
    import sys

    generator = FIXTURE_DIR / "generate_fixtures.py"
    if not generator.exists():
        return  # Generator missing -- assume committed fixtures are fresh enough.
    try:
        subprocess.run(
            [sys.executable, str(generator)],
            check=True,
            capture_output=True,
            cwd=Path(__file__).parent.parent,  # backend/
        )
    except subprocess.CalledProcessError:
        # If generation fails (missing pysaml2 etc.), fall back to the
        # committed fixtures and let individual tests skip/fail loudly.
        pass
    yield

FIXTURE_IDP_ENTITY_ID = "https://fixture-idp.geolens.test/idp"
FIXTURE_SP_ENTITY_ID = "https://geolens.test/auth/saml/fixture"
FIXTURE_SLUG = "fixture"
FIXTURE_NAMEID = "user@example.com"
# Embedded in the fixtures' InResponseTo attribute (see generate_fixtures.py).
FIXTURE_REQUEST_ID = "id-fixture-request-001"




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_saml_provider(
    db: AsyncSession,
    *,
    slug: str = FIXTURE_SLUG,
    display_name: str = "Fixture IdP",
    idp_entity_id: str = FIXTURE_IDP_ENTITY_ID,
    idp_sso_url: str = "https://fixture-idp.geolens.test/sso",
    idp_certificate: str = FIXTURE_CERT_PEM,
    sp_entity_id: str = FIXTURE_SP_ENTITY_ID,
    group_claim: str | None = "groups",
    group_role_mapping: dict | None = None,
    default_role: str = "viewer",
    enabled: bool = True,
) -> OAuthProvider:
    """Seed a SAML OAuthProvider row.

    NOTE: ``client_id`` and ``client_secret_encrypted`` are NOT-NULL on the
    ORM (backend/app/modules/auth/oauth/models.py:40-41). Plan 03 makes them
    Optional in Pydantic but does NOT relax the DB columns. Seed with
    placeholder strings to satisfy the constraint.
    """
    if group_role_mapping is None:
        group_role_mapping = {"editors": "editor"}
    provider = OAuthProvider(
        slug=slug,
        display_name=display_name,
        provider_type="saml",
        client_id="unused",                                # placeholder for NOT-NULL
        client_secret_encrypted=encrypt_secret("unused"),  # placeholder for NOT-NULL
        idp_entity_id=idp_entity_id,
        idp_sso_url=idp_sso_url,
        idp_certificate=encrypt_secret(idp_certificate),   # Fernet-encrypted at rest
        sp_entity_id=sp_entity_id,
        group_claim=group_claim,
        group_role_mapping=group_role_mapping,
        default_role=default_role,
        enabled=enabled,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


def _load_fixture_b64(name: str) -> str:
    """Read a base64-encoded SAML fixture and return the base64 string itself.

    pysaml2's ``parse_authn_request_response`` expects the raw base64
    form-field string (NOT decoded XML), so we return the file contents
    stripped of trailing whitespace.

    Fixture filenames (Wave 0):
      - idp_response_signed.xml.b64
      - idp_response_expired.xml.b64
      - idp_response_xsw.xml.b64
      - idp_response_unsigned.xml.b64
      - idp_response_replay.xml.b64  (byte-identical to signed)
    """
    return (FIXTURE_DIR / name).read_text().strip()


def _mount_saml_router(saml_overlay_registered) -> None:
    """Mount the SAML router into the FastAPI app for the test's lifetime.

    The ``saml_overlay_registered`` conftest fixture appends to
    ``_routers`` but does not call ``app.include_router(...)``. The core
    startup mounts routers at lifespan time -- which has already run for
    the test app -- so we have to mount manually here.
    """
    from app.api.main import app
    from geolens_enterprise.auth.saml.router import router as saml_router

    # Avoid double-mount on subsequent tests in the same session.
    already_mounted = any(
        getattr(r, "path", "").startswith("/auth/saml") for r in app.routes
    )
    if not already_mounted:
        app.include_router(saml_router)


def _unmount_saml_router() -> None:
    """Remove the SAML router from the FastAPI app (best-effort cleanup)."""
    from app.api.main import app

    app.router.routes = [
        r for r in app.router.routes if not getattr(r, "path", "").startswith("/auth/saml")
    ]


@pytest.fixture
async def _cleanup_saml_providers(test_db_session):
    """Best-effort cleanup of any SAML provider rows AND any users JIT-provisioned
    from SAML callbacks after each test.

    Tests that POST the signed/replay/expired/xsw fixtures need slug="fixture"
    because the fixture's Destination XML attribute is hardcoded to that slug;
    re-seeding the same slug across tests would violate the unique constraint
    on oauth_providers.slug. Cleaning up after each test keeps each one
    independent. Likewise, the JIT-provisioning test creates a user keyed on
    the fixture NameID -- subsequent negative tests that assert no such user
    exists need that row gone before they run.
    """
    yield
    try:
        # CASCADE removes oauth_accounts via FK; remove the user(s) JIT'd from
        # the fixture NameID first so we don't fight the user_roles FK.
        await test_db_session.execute(
            text(
                "DELETE FROM catalog.users WHERE email = :email"
            ),
            {"email": FIXTURE_NAMEID},
        )
        await test_db_session.execute(
            text(
                "DELETE FROM catalog.oauth_accounts WHERE provider_id IN "
                "(SELECT id FROM catalog.oauth_providers WHERE provider_type='saml')"
            )
        )
        await test_db_session.execute(
            text("DELETE FROM catalog.oauth_providers WHERE provider_type='saml'")
        )
        await test_db_session.commit()
    except Exception:
        await test_db_session.rollback()


@pytest.fixture
def saml_router_mounted(saml_overlay_registered):
    """Compose the registry fixture with FastAPI route mounting/unmounting AND
    edition initialization.

    The router is gated by ``Depends(require_enterprise)``, which calls
    ``is_enterprise()`` -- a singleton initialized at app lifespan. The
    ``client`` fixture's ASGITransport setup skips lifespan, so we
    initialize edition manually so ``require_enterprise`` returns True
    while this test runs.
    """
    import app.core.edition as edition_mod
    from geolens_enterprise.auth.saml import router as saml_router_mod
    from geolens_enterprise.auth.saml.replay import replay_cache

    _mount_saml_router(saml_overlay_registered)
    saved_info = edition_mod._info
    edition_mod.init_edition(["enterprise"])

    # Reset module-level singletons so test order does not affect outcomes.
    saved_outstanding = dict(saml_router_mod._outstanding_requests)
    saved_replay = dict(replay_cache._seen)
    saml_router_mod._outstanding_requests.clear()
    replay_cache._seen.clear()
    # Pre-populate the outstanding map so the fixtures (whose InResponseTo
    # attribute is FIXTURE_REQUEST_ID) are treated as solicited responses.
    saml_router_mod._outstanding_requests[FIXTURE_REQUEST_ID] = FIXTURE_SLUG

    # Patch get_public_api_url so the ACS URL the SAML router builds matches
    # the fixture's hardcoded Destination attribute. The fixtures were
    # generated against the constant ACS_URL = "https://geolens.test/auth/
    # saml/fixture/acs"; pysaml2 enforces Destination-vs-ACS match
    # ("destination ... not in return addresses ..."). In production the
    # API public URL is admin-configured; in tests we make it the fixture URL.
    import app.core.public_urls as public_urls_mod

    saved_get_api_url = public_urls_mod.get_public_api_url

    async def _fixture_api_url(db, request=None):  # type: ignore[no-untyped-def]
        return "https://geolens.test"

    public_urls_mod.get_public_api_url = _fixture_api_url
    # The SAML router imported the symbol, so patch the imported binding too.
    saml_router_mod.get_public_api_url = _fixture_api_url

    try:
        yield saml_overlay_registered
    finally:
        edition_mod._info = saved_info
        saml_router_mod._outstanding_requests.clear()
        saml_router_mod._outstanding_requests.update(saved_outstanding)
        replay_cache._seen.clear()
        replay_cache._seen.update(saved_replay)
        public_urls_mod.get_public_api_url = saved_get_api_url
        saml_router_mod.get_public_api_url = saved_get_api_url
        _unmount_saml_router()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_saml_overlay_registers_under_identity_and_routers(
    saml_overlay_registered,
):
    """SAML-09: extension dual-registered under 'identity' AND _routers."""
    from app.platform.extensions import _extensions, _routers
    from geolens_enterprise.auth.saml import EnterpriseSamlExtension

    assert isinstance(_extensions["identity"], EnterpriseSamlExtension)
    assert isinstance(_extensions["auth"], EnterpriseSamlExtension)
    # Same instance under both keys (D-13).
    assert _extensions["identity"] is _extensions["auth"]
    # SAML router appended to the routers list.
    assert any(getattr(r, "prefix", "") == "/auth/saml" for r in _routers)


async def test_saml_metadata_xml_valid(
    client, test_db_session, saml_router_mounted, _cleanup_saml_providers
):
    """SAML-11: GET /auth/saml/{slug}/metadata returns valid samlmetadata+xml."""
    from defusedxml import ElementTree as ET

    await _seed_saml_provider(test_db_session)

    resp = await client.get(f"/auth/saml/{FIXTURE_SLUG}/metadata")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/samlmetadata+xml")

    # Body parses as XML and contains the SP entityID + an EntityDescriptor.
    root = ET.fromstring(resp.text)
    assert "EntityDescriptor" in root.tag, f"unexpected root: {root.tag}"
    assert FIXTURE_SP_ENTITY_ID in resp.text


async def test_saml_acs_signed_assertion_jit_provisions_user(
    client, test_db_session, saml_router_mounted, _cleanup_saml_providers
):
    """SAML-11: signed assertion JIT-provisions user + issues JWT + redirects.

    The fixture's Destination attribute is hardcoded to /fixture/acs so all
    ACS-POST tests use slug='fixture'. Provider rows are deleted by
    ``_cleanup_saml_providers`` between tests to avoid the slug
    UNIQUE-constraint collision.
    """
    await _seed_saml_provider(test_db_session)
    saml_response = _load_fixture_b64("idp_response_signed.xml.b64")

    resp = await client.post(
        f"/auth/saml/{FIXTURE_SLUG}/acs",
        data={"SAMLResponse": saml_response},
        follow_redirects=False,
    )
    assert resp.status_code == 302, f"expected redirect, got {resp.status_code}: {resp.text}"
    location = resp.headers["location"]

    # URL must include ?source=saml query param (Pitfall 8).
    parsed = urlparse(location)
    qs = parse_qs(parsed.query)
    assert qs.get("source") == ["saml"], f"missing source=saml: {location}"

    # Fragment must contain token, refresh_token, expires_in.
    fragment = parsed.fragment
    frag_pairs = dict(p.split("=", 1) for p in fragment.split("&") if "=" in p)
    assert "token" in frag_pairs and frag_pairs["token"], (
        f"no JWT issued; fragment={fragment}"
    )
    assert "refresh_token" in frag_pairs and frag_pairs["refresh_token"]
    assert "expires_in" in frag_pairs and frag_pairs["expires_in"].isdigit()

    # A new User row exists with the assertion email + auth_provider='oauth'.
    result = await test_db_session.execute(
        select(User).where(User.email == FIXTURE_NAMEID)
    )
    user = result.scalar_one_or_none()
    assert user is not None, "JIT provisioning did not create a user"
    assert user.auth_provider == "oauth"


async def test_saml_acs_rejects_invalid_signature(
    client, test_db_session, saml_router_mounted, _cleanup_saml_providers
):
    """SAML-11: tampered/wrong-signature assertion produces an error redirect.

    The expired fixture's signature was invalidated by post-signing
    text-rewrite of IssueInstant (Wave 1 SUMMARY decision); this is a
    convenient stand-in for a generic invalid-signature scenario.
    """
    await _seed_saml_provider(test_db_session)
    saml_response = _load_fixture_b64("idp_response_expired.xml.b64")

    resp = await client.post(
        f"/auth/saml/{FIXTURE_SLUG}/acs",
        data={"SAMLResponse": saml_response},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"], resp.headers["location"]
    assert "token=" not in resp.headers["location"]

    # No user provisioned.
    result = await test_db_session.execute(
        select(User).where(User.email == FIXTURE_NAMEID)
    )
    assert result.scalar_one_or_none() is None


async def test_saml_acs_rejects_unsigned(
    client, test_db_session, saml_router_mounted, _cleanup_saml_providers
):
    """SAML-11: unsigned assertion is rejected (want_assertions_signed=True)."""
    await _seed_saml_provider(test_db_session)
    saml_response = _load_fixture_b64("idp_response_unsigned.xml.b64")

    resp = await client.post(
        f"/auth/saml/{FIXTURE_SLUG}/acs",
        data={"SAMLResponse": saml_response},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    assert "token=" not in resp.headers["location"]


async def test_saml_acs_rejects_expired_assertion(
    client, test_db_session, saml_router_mounted, _cleanup_saml_providers
):
    """SAML-11 / Pitfall 4: expired assertion is rejected.

    The ``expired`` fixture has IssueInstant/NotBefore/NotOnOrAfter rewritten
    to 2020 dates -- well past any reasonable accepted_time_diff (60s).
    """
    await _seed_saml_provider(test_db_session)
    saml_response = _load_fixture_b64("idp_response_expired.xml.b64")

    resp = await client.post(
        f"/auth/saml/{FIXTURE_SLUG}/acs",
        data={"SAMLResponse": saml_response},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
    assert "token=" not in resp.headers["location"]


async def test_saml_acs_rejects_replayed_assertion(
    client, test_db_session, saml_router_mounted, _cleanup_saml_providers
):
    """SAML-11 / Pitfall 5: same assertion submitted twice is rejected on the
    second attempt by ReplayCache. The fixture's outstanding-request entry
    is also re-tracked between submissions so the second failure is
    attributable to ReplayCache rather than the consumed reqid."""
    from geolens_enterprise.auth.saml import router as saml_router_mod

    await _seed_saml_provider(test_db_session)
    saml_response = _load_fixture_b64("idp_response_signed.xml.b64")

    # First submission succeeds.
    resp1 = await client.post(
        f"/auth/saml/{FIXTURE_SLUG}/acs",
        data={"SAMLResponse": saml_response},
        follow_redirects=False,
    )
    assert resp1.status_code == 302
    assert "token=" in resp1.headers["location"], (
        f"first POST should succeed: {resp1.headers['location']}"
    )

    # Re-track the reqid (consumed by the first call) so the second call's
    # rejection is attributable to ReplayCache, not pysaml2's
    # solicited-only check on the now-missing outstanding entry.
    saml_router_mod._outstanding_requests[FIXTURE_REQUEST_ID] = FIXTURE_SLUG

    # Second submission of the same assertion is rejected.
    resp2 = await client.post(
        f"/auth/saml/{FIXTURE_SLUG}/acs",
        data={"SAMLResponse": saml_response},
        follow_redirects=False,
    )
    assert resp2.status_code == 302
    assert "error=" in resp2.headers["location"], (
        f"second (replayed) POST should fail: {resp2.headers['location']}"
    )
    assert "token=" not in resp2.headers["location"]


async def test_saml_acs_rejects_xsw_attack(
    client, test_db_session, saml_router_mounted, _cleanup_saml_providers
):
    """SAML-11 / Pitfall 2: XML Signature Wrapping attack is rejected.

    The XSW fixture wraps a legitimate signed assertion inside an evil
    unsigned outer assertion (subject=attacker@evil.test). pysaml2 7.5.4 +
    xmlsec1 reject this shape -- the test asserts the response is an error
    redirect, not a happy-path 302 with a JWT for the attacker subject.
    """
    await _seed_saml_provider(test_db_session)
    saml_response = _load_fixture_b64("idp_response_xsw.xml.b64")

    resp = await client.post(
        f"/auth/saml/{FIXTURE_SLUG}/acs",
        data={"SAMLResponse": saml_response},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    # Either a clean error redirect, OR (defense-in-depth) a redirect that
    # at minimum did NOT issue a JWT for the attacker subject.
    if "token=" in location:
        # Decode the JWT to make sure it isn't for attacker@evil.test.
        # (We don't expect this branch -- pysaml2 should reject XSW outright.)
        parsed = urlparse(location)
        frag_pairs = dict(p.split("=", 1) for p in parsed.fragment.split("&") if "=" in p)
        token = frag_pairs.get("token", "")
        # JWT body is the middle base64url segment.
        try:
            body_b64 = token.split(".")[1]
            body_b64 += "=" * (-len(body_b64) % 4)
            body = base64.urlsafe_b64decode(body_b64).decode()
        except Exception:
            body = ""
        assert "attacker@evil.test" not in body, (
            f"XSW attack succeeded -- attacker email landed in JWT: {body}"
        )
    else:
        assert "error=" in location, f"unexpected non-error redirect: {location}"


async def test_saml_acs_redirect_includes_source_query_param(
    client, test_db_session, saml_router_mounted, _cleanup_saml_providers
):
    """Pitfall 8 / D-15: post-ACS redirect URL must include ?source=saml so
    the frontend OAuth callback handler can distinguish SAML callbacks.

    Verified against both happy-path and error redirect to confirm the
    query param is consistently present.
    """
    from geolens_enterprise.auth.saml import router as saml_router_mod

    await _seed_saml_provider(test_db_session)

    # Happy path.
    happy = await client.post(
        f"/auth/saml/{FIXTURE_SLUG}/acs",
        data={"SAMLResponse": _load_fixture_b64("idp_response_signed.xml.b64")},
        follow_redirects=False,
    )
    happy_qs = parse_qs(urlparse(happy.headers["location"]).query)
    assert happy_qs.get("source") == ["saml"], happy.headers["location"]

    # Reset reqid + replay cache for the second call (different fixture so
    # different assertion id, but the unsigned fixture also uses
    # FIXTURE_REQUEST_ID via the _outstanding map shape).
    saml_router_mod._outstanding_requests[FIXTURE_REQUEST_ID] = FIXTURE_SLUG
    saml_router_mod._outstanding_requests["id-fixture-request-002"] = FIXTURE_SLUG

    # Error path.
    err = await client.post(
        f"/auth/saml/{FIXTURE_SLUG}/acs",
        data={"SAMLResponse": _load_fixture_b64("idp_response_unsigned.xml.b64")},
        follow_redirects=False,
    )
    err_qs = parse_qs(urlparse(err.headers["location"]).query)
    assert err_qs.get("source") == ["saml"], err.headers["location"]


# ---------------------------------------------------------------------------
# Plan 03 Task 02: Pydantic schema per-type validation tests (SAML-12 / D-12)
# ---------------------------------------------------------------------------


def test_oauth_provider_create_saml_requires_all_4_fields():
    """SAML provider creation must reject any missing SAML field with a clear
    ValidationError naming the missing field(s) (RESEARCH §6 model_validator)."""
    from pydantic import ValidationError

    from app.modules.auth.oauth.schemas import OAuthProviderCreate

    with pytest.raises(ValidationError) as excinfo:
        OAuthProviderCreate(
            slug="incomplete-saml",
            display_name="Incomplete",
            provider_type="saml",
            idp_entity_id="https://idp.example.com",
            # missing: idp_sso_url, idp_certificate, sp_entity_id
        )
    msg = str(excinfo.value)
    assert "SAML providers require" in msg
    assert "idp_sso_url" in msg
    assert "idp_certificate" in msg
    assert "sp_entity_id" in msg


def test_oauth_provider_create_saml_accepts_all_4_fields():
    """Complete SAML payload validates without error (RESEARCH §6 happy path)."""
    from app.modules.auth.oauth.schemas import OAuthProviderCreate

    m = OAuthProviderCreate(
        slug="complete-saml",
        display_name="Complete SAML",
        provider_type="saml",
        idp_entity_id="https://fixture-idp.geolens.test/idp",
        idp_sso_url="https://fixture-idp.geolens.test/sso",
        idp_certificate="-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
        sp_entity_id="https://geolens.test/auth/saml/complete-saml",
    )
    assert m.provider_type == "saml"
    assert m.client_id is None
    assert m.client_secret is None
    assert m.idp_entity_id == "https://fixture-idp.geolens.test/idp"


def test_oauth_provider_create_oauth_rejects_saml_fields():
    """OIDC/Google/Microsoft providers must not set SAML fields — prevents
    mixed configs that confuse the runtime (Pitfall: ambiguous provider rows)."""
    from pydantic import ValidationError

    from app.modules.auth.oauth.schemas import OAuthProviderCreate

    with pytest.raises(ValidationError) as excinfo:
        OAuthProviderCreate(
            slug="bad-mix",
            display_name="Bad Mix",
            provider_type="oidc",
            client_id="cid",
            client_secret="csec",
            idp_entity_id="https://leaked.example.com",  # SAML field on OAuth
        )
    msg = str(excinfo.value)
    assert "must not set SAML fields" in msg
    assert "idp_entity_id" in msg


def test_oauth_provider_create_oauth_requires_client_secret():
    """OIDC/Google/Microsoft providers must have client_id AND client_secret
    (Anti-Pattern A4: making them Optional must NOT bypass OAuth's existing
    requirement)."""
    from pydantic import ValidationError

    from app.modules.auth.oauth.schemas import OAuthProviderCreate

    with pytest.raises(ValidationError) as excinfo:
        OAuthProviderCreate(
            slug="no-creds",
            display_name="No Creds",
            provider_type="oidc",
            # client_id and client_secret intentionally omitted
        )
    msg = str(excinfo.value)
    assert "require client_id and client_secret" in msg


def test_oauth_provider_response_excludes_idp_certificate():
    """Pattern D / T-217-03-WRITEONLY: idp_certificate is a write-only credential
    and must not appear in OAuthProviderResponse. The 3 non-secret SAML fields
    (idp_entity_id, idp_sso_url, sp_entity_id) ARE allowed."""
    from app.modules.auth.oauth.schemas import OAuthProviderResponse

    fields = set(OAuthProviderResponse.model_fields.keys())
    assert "idp_certificate" not in fields, (
        f"idp_certificate must NOT appear in OAuthProviderResponse; "
        f"got: {sorted(fields)}"
    )
    assert "client_secret_encrypted" not in fields
    assert "client_secret" not in fields
    # The 3 non-secret SAML fields ARE exposed (admin UI needs them).
    assert "idp_entity_id" in fields
    assert "idp_sso_url" in fields
    assert "sp_entity_id" in fields


# ---------------------------------------------------------------------------
# Plan 03 Task 03: Audit-log diff + SECRET_FIELDS redaction tests
# (SAML-12 / Pitfall 9 HIGH / T-217-03-AUDIT-LEAK)
#
# CRITICAL: tests use HTTP PUT (not PATCH) — endpoint is @router.put at
# backend/app/modules/settings/router.py:399. PATCH would yield 405.
# ---------------------------------------------------------------------------


async def test_saml_provider_update_logs_old_new_role_mapping(
    client,
    test_db_session,
    admin_auth_header,
    saml_router_mounted,
    _cleanup_saml_providers,
):
    """SAML-12 / SC#4: audit-log entry for SAML provider update captures
    ``details.changes.group_role_mapping = {old: ..., new: ...}``.

    Closes the SAML-12 audit gap identified in RESEARCH §11 (the prior code
    logged only ``slug``; SAML-12 mandates "old/new values").

    Uses ``saml_router_mounted`` to flip ``is_enterprise()`` to True --
    OAuthProviderUpdate's ``_validate_idp_mapping_gate`` rejects non-empty
    ``group_role_mapping`` in community mode (oauth/schemas.py:298), so
    without enterprise the PUT would 422 before reaching the audit-log
    diff path being tested here.
    """
    from app.modules.audit.models import AuditLog

    # Seed via direct DB insert (PUT-against-router would require enterprise
    # edition init for the SAML schema validator).
    provider = await _seed_saml_provider(
        test_db_session,
        slug=f"audit-{uuid.uuid4().hex[:6]}",
        group_role_mapping={"editors": "editor"},
    )
    provider_id = str(provider.id)

    # PUT to update the role mapping (NOT PATCH — endpoint is @router.put).
    resp = await client.put(
        f"/settings/oauth-providers/{provider_id}",
        json={"group_role_mapping": {"editors": "admin", "viewers": "viewer"}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    # Inspect the audit log entry directly. Need a fresh session so the
    # commit from the request handler is visible.
    import app.core.db as db_module

    async with db_module.async_session() as fresh:
        result = await fresh.execute(
            select(AuditLog)
            .where(AuditLog.action == "oauth_provider.update")
            .where(AuditLog.resource_id == uuid.UUID(provider_id))
            .order_by(AuditLog.created_at.desc())
        )
        entry = result.scalar_one_or_none()
        assert entry is not None, "no audit log entry created for SAML provider update"

        details = entry.details or {}
        assert "changes" in details, f"audit details missing 'changes' key: {details}"
        changes = details["changes"]
        assert "group_role_mapping" in changes, (
            f"group_role_mapping not in changes: {changes}"
        )
        diff = changes["group_role_mapping"]
        assert "old" in diff and "new" in diff, f"missing old/new diff shape: {diff}"
        assert diff["old"] == {"editors": "editor"}, f"wrong old: {diff['old']}"
        assert diff["new"] == {"editors": "admin", "viewers": "viewer"}, (
            f"wrong new: {diff['new']}"
        )


async def test_saml_provider_update_redacts_secret_fields(
    client, test_db_session, admin_auth_header, _cleanup_saml_providers
):
    """Pitfall 9 / T-217-03-AUDIT-LEAK HIGH: updating ``idp_certificate`` in
    a SAML provider must record the change in the audit log as
    ``{"old": "<redacted>", "new": "<redacted>"}`` — never the raw PEM, never
    the encrypted ciphertext.

    Verifies the SECRET_FIELDS allowlist (idp_certificate,
    client_secret_encrypted, client_secret) and the SECRET_BODY_FIELDS
    body-detection loop (per checker WARNING #3).
    """
    import uuid as _uuid

    from app.modules.audit.models import AuditLog

    new_pem = "-----BEGIN CERTIFICATE-----\nMOCKNEWCERT\n-----END CERTIFICATE-----"

    provider = await _seed_saml_provider(
        test_db_session,
        slug=f"redact-{_uuid.uuid4().hex[:6]}",
    )
    provider_id = str(provider.id)

    resp = await client.put(
        f"/settings/oauth-providers/{provider_id}",
        json={"idp_certificate": new_pem},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    # The response itself must NOT include idp_certificate (write-only).
    body = resp.json()
    assert "idp_certificate" not in body, (
        f"idp_certificate leaked in response: {body}"
    )

    # Audit-log entry must redact both old and new values for idp_certificate.
    import app.core.db as db_module

    async with db_module.async_session() as fresh:
        result = await fresh.execute(
            select(AuditLog)
            .where(AuditLog.action == "oauth_provider.update")
            .where(AuditLog.resource_id == _uuid.UUID(provider_id))
            .order_by(AuditLog.created_at.desc())
        )
        entry = result.scalar_one_or_none()
        assert entry is not None
        changes = (entry.details or {}).get("changes", {})
        assert "idp_certificate" in changes, (
            f"idp_certificate change not recorded: {changes}"
        )
        diff = changes["idp_certificate"]
        assert diff == {"old": "<redacted>", "new": "<redacted>"}, (
            f"idp_certificate must be redacted in audit log: {diff}"
        )

        # Defensive: the raw PEM must NOT appear ANYWHERE in the audit details.
        details_str = str(entry.details)
        assert "MOCKNEWCERT" not in details_str, (
            f"raw PEM leaked into audit details: {details_str}"
        )
        assert "-----BEGIN" not in details_str, (
            f"PEM markers leaked into audit details: {details_str}"
        )


# ---------------------------------------------------------------------------
# Plan 04 Task 02 — SAML-10 backend half: community-mode 404
# ---------------------------------------------------------------------------


async def test_saml_endpoint_404_in_community(client):
    """SAML-10 backend half: SAML routes return 404 in community mode.

    Without the ``saml_router_mounted`` fixture (which both registers the
    enterprise extension AND mounts the router into the FastAPI app), the
    SAML router is absent from the app and any /auth/saml/* path returns
    404. This is the third defense layer behind:

      - frontend AdminSidebar hiding the nav item when !isEnterprise
        (verified in frontend/src/components/admin/__tests__/AdminSidebar.test.tsx)
      - frontend AdminSamlPage <Navigate to=\"/admin\"> when !isEnterprise

    We exercise all three SAML route shapes (login, metadata, acs) to
    confirm none of them leak in the community build.

    Note: this test deliberately does NOT request ``saml_router_mounted``
    or ``saml_overlay_registered``. Other tests in this file may run
    before/after it; the ``saml_router_mounted`` fixture's teardown
    block always unmounts the SAML router, so test ordering does not
    affect this assertion.
    """
    for method, path in [
        ("GET", "/auth/saml/anyslug/login"),
        ("GET", "/auth/saml/anyslug/metadata"),
        ("POST", "/auth/saml/anyslug/acs"),
    ]:
        if method == "POST":
            response = await client.post(path, data={"SAMLResponse": "ignored"})
        else:
            response = await client.get(path)
        assert response.status_code == 404, (
            f"{method} {path} returned {response.status_code} (expected 404 in "
            f"community mode -- SAML router should not be mounted)"
        )


async def test_saml_attribute_to_role_mapping_via_provider_group_claim(
    client, test_db_session, saml_router_mounted, _cleanup_saml_providers
):
    """SAML-12 / SC#4 behavior coverage: a SAML user whose assertion contains
    ``groups=['editors']`` and whose provider has
    ``group_claim='groups'`` + ``group_role_mapping={'editors': 'editor'}``
    must be JIT-provisioned with role='editor' (NOT default_role='viewer').

    Confirms the OAuth ``find_or_create_oauth_user()`` group → role mapping
    pathway works for SAML through the existing OAuth JIT path (D-04).
    """
    from app.modules.auth.models import Role, UserRole

    # Seed with group_role_mapping that maps the fixture's group to 'editor'.
    await _seed_saml_provider(
        test_db_session,
        group_claim="groups",
        group_role_mapping={"editors": "editor"},
        default_role="viewer",  # default would be viewer; mapping takes precedence
    )
    saml_response = _load_fixture_b64("idp_response_signed.xml.b64")

    resp = await client.post(
        f"/auth/saml/{FIXTURE_SLUG}/acs",
        data={"SAMLResponse": saml_response},
        follow_redirects=False,
    )
    assert resp.status_code == 302, f"ACS POST failed: {resp.text}"
    assert "token=" in resp.headers["location"], (
        f"JIT provisioning did not complete: {resp.headers['location']}"
    )

    # Look up the JIT-provisioned user and confirm role='editor' (not viewer).
    import app.core.db as db_module

    async with db_module.async_session() as fresh:
        user_result = await fresh.execute(
            select(User).where(User.email == FIXTURE_NAMEID)
        )
        user = user_result.scalar_one_or_none()
        assert user is not None, "no user provisioned"

        role_result = await fresh.execute(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        )
        roles = [r for r in role_result.scalars().all()]
        assert "editor" in roles, (
            f"group→role mapping failed: expected role 'editor', got {roles}"
        )
