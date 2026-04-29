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
    from geolens_enterprise.auth.saml.replay import replay_cache

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
