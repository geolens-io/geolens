---
phase: 217-auth-saml-enterprise
plan: 02
subsystem: auth
tags: [auth, saml, enterprise, scaffold, modernization, hardening, identity-protocol, dual-registration]

# Dependency graph
requires:
  - phase: 217-01
    provides: e002_add_saml_columns migration; saml_overlay_registered conftest fixture; 9 SAML test fixtures (PEM cert/key + 5 SAMLResponse XML.b64) + reproducibility script
  - phase: 214-identity-protocol-extract
    provides: IdentityExtension Protocol surface, get_identity_extension() typed accessor, DefaultIdentityExtension no-op
provides:
  - Modernized SAML scaffold (router/config) -- all eight pre-v13.0 import paths replaced with current core paths
  - GET /auth/saml/{slug}/metadata endpoint (D-08) returning samlmetadata+xml
  - EnterpriseSamlExtension implementing both AuthExtension AND IdentityExtension structurally (D-13)
  - Dual-registration of EnterpriseSamlExtension under registry['auth'] AND registry['identity'] (D-06 / D-13)
  - accepted_time_diff=60 in Saml2Config (Pitfall 4)
  - ?source=saml query param + correlation_id exception handler in ACS redirect (D-07 / Pitfall 8)
  - 9 SAML overlay integration tests in backend/tests/test_saml_overlay.py
  - 4 standalone SAML config tests + 5 standalone replay-cache tests + 3 new registration tests in geolens-enterprise
  - In-process outstanding-AuthnRequest tracker for solicited-only check (allows D-15 hardening to actually work)
  - PEM-header stripping on inlined IdP certificate (xmlsec1 compatibility)
  - SAML columns declared on OAuthProvider ORM (4 nullable fields + relaxed CHECK literal)
  - conftest.py change to ensure enterprise migration branch participates in test-DB upgrade
affects: [217-03, 217-04, 217-05]

# Tech tracking
tech-stack:
  added:
    - "geolens-enterprise installed editable into the worktree backend venv (required so the saml_overlay_registered conftest fixture can deferred-import the EnterpriseSamlExtension class and so e002_add_saml_columns runs during test-DB setup)"
  patterns:
    - "OAuth callback verbatim mirror: SAML ACS endpoint follows backend/app/modules/auth/oauth/router.py:85-148 step-for-step (frontend_url before try, correlation_id exception, fragment-encoded JWT redirect)"
    - "Single-class dual-Protocol implementation (D-13): EnterpriseSamlExtension structurally satisfies both AuthExtension AND IdentityExtension; same instance dual-registered under registry['auth'] AND registry['identity']"
    - "Outstanding-AuthnRequest tracking: in-process dict populated by saml_login() and consumed by saml_acs() so allow_unsolicited=False (D-15) can actually accept solicited responses; mirrors ReplayCache's single-process limitation"
    - "Session-scoped fixture-regeneration: pytest session-autouse fixture calls generate_fixtures.py at start so SAML assertion timestamps stay within the 15-minute validity window"
    - "Test-time SAML provider cleanup: per-test fixture deletes oauth_providers + oauth_accounts + JIT-provisioned users so successive tests can re-seed slug='fixture' (the fixture's hardcoded Destination requires it)"

key-files:
  created:
    - "backend/tests/test_saml_overlay.py (9 integration tests + 2 helper fixtures + 2 helper functions)"
    - "geolens-enterprise/tests/test_saml_config.py (4 standalone tests for build_saml_client + _build_idp_metadata_xml)"
    - "geolens-enterprise/tests/test_replay_cache.py (5 standalone tests for ReplayCache TTL + thread safety)"
  modified:
    - "geolens-enterprise/geolens_enterprise/auth/saml/router.py (modernized imports, added metadata endpoint, ADFS URN attribute keys, ?source=saml + correlation_id exception, outstanding-request tracker)"
    - "geolens-enterprise/geolens_enterprise/auth/saml/config.py (modernized imports, added accepted_time_diff=60, _strip_pem_headers helper)"
    - "geolens-enterprise/geolens_enterprise/auth/saml/__init__.py (extended EnterpriseSamlExtension with no-op resolve_identity_from_token)"
    - "geolens-enterprise/geolens_enterprise/__init__.py (dual-register saml_ext under registry['auth'] AND registry['identity']; rename _get_auth_extension -> _get_saml_extension)"
    - "geolens-enterprise/tests/test_registration.py (updated stale down_revision assertion + added 3 new tests)"
    - "backend/app/modules/auth/oauth/models.py (declared 4 nullable SAML columns + relaxed CHECK literal)"
    - "backend/tests/conftest.py (pre-set version_locations from geolens.migrations entry-point + use 'heads' plural)"
    - "backend/tests/test_extensions.py (autouse fixture patches entry_points to default-empty for test isolation)"

key-decisions:
  - "Installed geolens-enterprise editable into the worktree backend venv. Required so the saml_overlay_registered fixture can import EnterpriseSamlExtension and so e002_add_saml_columns runs at test-DB setup. Side effect: cryptography downgraded to 43.0.3 by pysaml2's transitive dep but uv re-resolved to the pinned 46.0.7 on next invocation; verified."
  - "Pre-set version_locations from geolens.migrations entry-point group BEFORE command.upgrade() rather than relying on env.py to mutate cfg post-construction. ScriptDirectory caches version_locations from the cfg at construction time, so env.py-time mutations don't propagate to the upgrade walk. This was a real bug -- enterprise migrations would silently NOT run unless the test conftest pre-set the option."
  - "Patched entry_points to default-empty in the test_extensions.py autouse fixture. With geolens-enterprise editable-installed, load_extensions() would otherwise discover and register the production extensions -- breaking test_load_extensions_empty, test_list_extensions, test_get_extension_routers_empty. Each test that needs extensions can opt-in via its own with patch(...). Strict-improvement isolation."
  - "Added in-process _outstanding_requests dict to the SAML router. Without it, the existing scaffold could not actually process solicited responses (allow_unsolicited=False rejects everything when there's no outstanding queue). Single-process limitation matches ReplayCache; documented inline. This was a real pre-existing bug that only surfaced under integration testing."
  - "Added _strip_pem_headers() helper to _build_idp_metadata_xml. The scaffold inlined the FULL PEM (with -----BEGIN/END CERTIFICATE----- markers) into <ds:X509Certificate>; xmlsec1 fails to parse the resulting metadata file. Pre-existing scaffold bug."
  - "Declared the 4 nullable SAML columns on the OAuthProvider ORM model in core. Plan 03 nominally owns this, but without it the SAML router cannot read provider.idp_entity_id etc. -- so Plan 02's tests cannot exercise the ACS path. Made minimal declaration only; Pydantic schema validation + per-type discriminators land in Plan 03."
  - "Tests use a session-autouse fixture that re-runs generate_fixtures.py at session start so SAML assertion timestamps stay within the 15-minute validity window. The committed .xml.b64 files remain reproducible snapshots; tests always generate fresh ones to avoid the wall-clock-vs-fixture-time-window race."
  - "Per-test cleanup of SAML provider rows (and JIT-provisioned users keyed on the fixture NameID). The fixture's hardcoded Destination attribute (/fixture/acs) forces all ACS-POST tests to use slug='fixture'; cleanup means each test starts from a clean slate without violating the unique-slug constraint."

patterns-established:
  - "Pre-set version_locations from entry-points before alembic command.upgrade()"
  - "Test-time entry_points isolation via autouse fixture patching to default-empty"
  - "In-process outstanding-AuthnRequest tracker with single-process limitation documentation"
  - "PEM-header stripping for XMLDSig <X509Certificate> content"
  - "Per-test SAML provider cleanup keyed on provider_type='saml' + fixture NameID"

requirements-completed: []  # SAML-09 / SAML-11 substantively progressed but not yet "phase-verified"; final close happens at Plan 05's verification gate

# Metrics
duration: ~31min
completed: 2026-04-29
---

# Phase 217 Plan 02: Modernize Scaffold + Dual-Protocol Registration + SAML Integration Tests Summary

**Modernized the pre-v13.0 SAML scaffold, dual-registered EnterpriseSamlExtension under both AuthExtension and IdentityExtension Protocol seams, added the SP metadata endpoint, fixed three pre-existing scaffold bugs that only surface under integration testing (xmlsec1 cert format, missing outstanding-request tracking, scaffold import paths), and shipped 9 SAML integration tests + 9 standalone enterprise tests covering registration, metadata, JIT provisioning, replay defense, XSW defense, signature/expiry rejection, and Pitfall 8 redirect param.**

## Performance

- **Duration:** ~31 min
- **Started:** 2026-04-29T13:49:07Z
- **Completed:** 2026-04-29T14:20:47Z
- **Tasks:** 3 (modernize scaffold; dual-register + standalone tests; integration tests)
- **Files modified:** 11 (5 in core worktree, 6 in enterprise repo)
- **Files created:** 3 (1 in core, 2 in enterprise)

## Accomplishments

- **Scaffold modernization (Task 01):** All eight pre-v13.0 import paths in `geolens-enterprise/auth/saml/{router,config}.py` replaced with current core paths (`app.modules.auth.*`, `app.core.*`, `app.platform.extensions.*`). Specifically: `app.core.dependencies.get_db` (NOT `app.api.deps` per the CONTEXT D-10 typo Anti-Pattern A2). Hard cutover, no compatibility shims (Anti-Pattern A1).
- **SP metadata endpoint (Task 01):** `GET /auth/saml/{slug}/metadata` returns `application/samlmetadata+xml` via pysaml2's `create_metadata_string(configfile=None, config=client.config, sign=False)` -- not hand-rolled XML (Anti-Pattern A7). Gated by router-level `Depends(require_enterprise)` so community returns 404.
- **Hardening additions (Task 01):** `accepted_time_diff: 60` added to Saml2Config (Pitfall 4); `?source=saml` query param added to ACS redirect (Pitfall 8); ACS exception handler replaced with the OAuth-mirroring `correlation_id` pattern (D-07 step 12); ADFS URN attribute keys added to `_extract_attr` (D-11): `http://schemas.microsoft.com/identity/claims/displayname` for displayName, `http://schemas.xmlsoap.org/claims/Group` for groups.
- **Single-class dual-Protocol implementation (Task 02):** `EnterpriseSamlExtension` extended with `async def resolve_identity_from_token(self, token, request, db) -> None` (no-op mirror of `DefaultIdentityExtension`). Zero base classes (Anti-Pattern A6: structural Protocol conformance only).
- **Dual-registration (Task 02):** `register_extensions()` now holds the SAML instance in a local `saml_ext` and registers the same object under both `registry["auth"]` AND `registry["identity"]`. Internal helper renamed `_get_auth_extension` -> `_get_saml_extension` for clarity.
- **Standalone enterprise tests (Task 02):** `tests/test_registration.py` extended with 3 new tests (dual-registration, no-op IdentityExtension, e002 migration discovery); `tests/test_saml_config.py` created with 4 tests (build_saml_client returns Saml2Client, accepted_time_diff=60, sp_entity_id propagation, want_assertions_signed=True, IdP metadata XML shape); `tests/test_replay_cache.py` created with 5 tests (insert/duplicate/distinct/TTL-expiry/thread-safe). 18 enterprise tests green (was 6 before this plan; 12 new + 1 repaired).
- **Integration tests (Task 03):** `backend/tests/test_saml_overlay.py` created with 9 integration tests covering all 8 plan-required scenarios plus the Pitfall 8 happy-path-and-error redirect verification:
  1. Extension dual-registers under registry['identity'] + _routers (SAML-09)
  2. GET /auth/saml/{slug}/metadata returns valid samlmetadata+xml (SAML-11)
  3. Signed assertion JIT-provisions user + issues JWT + redirects (SAML-11)
  4. Invalid-signature assertion produces error redirect (SAML-11)
  5. Unsigned assertion is rejected (SAML-11)
  6. Expired assertion is rejected (SAML-11 / Pitfall 4)
  7. Replayed assertion is rejected (SAML-11 / Pitfall 5)
  8. XSW attack assertion is rejected (SAML-11 / Pitfall 2)
  9. Both happy-path and error redirect include `?source=saml` (Pitfall 8)
- **Test infrastructure:** Added `_cleanup_saml_providers` fixture (deletes SAML providers + JIT'd users between tests), `saml_router_mounted` fixture (composes registry fixture + FastAPI route mounting + edition init + outstanding-request seeding + replay-cache reset + ACS-URL stub), and a session-autouse `_regenerate_saml_fixtures` fixture (re-runs generate_fixtures.py so timestamps stay within validity window).

## Task Commits

Each task was committed atomically; commits in two repos because Plan 02 spans both:

1. **Task 01 (enterprise repo):** `50a6ba3` -- modernize SAML scaffold imports + add metadata endpoint
2. **Task 02 (enterprise repo):** `204c10c` -- dual-register SAML extension + standalone enterprise tests
3. **Scaffold bug-fix during Task 03 (enterprise repo):** `d91db21` -- fix three pre-existing SAML scaffold bugs found during integration testing (PEM-header inlining, missing outstanding-request tracking, response-consumption hygiene)
4. **Task 03 (core worktree):** `542fc38d` -- SAML overlay integration tests + supporting infrastructure (model SAML cols, conftest version_locations, test_extensions isolation)

_Cross-repo note: enterprise repo commits land in `~/Code/geolens-enterprise` history independently of this worktree's branch; the core commits are on this worktree's branch and ship via the orchestrator merge._

## Files Created/Modified

### Core worktree
- `backend/app/modules/auth/oauth/models.py` -- declared 4 nullable SAML columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`); relaxed `chk_oauth_providers_type` literal to include `'saml'`
- `backend/tests/conftest.py` -- pre-set `version_locations` from `geolens.migrations` entry-point group; switched `command.upgrade(..., "head")` to `"heads"` for branch-aware upgrade
- `backend/tests/test_extensions.py` -- extended autouse `_clean_registry` fixture to patch `entry_points` to default-empty
- `backend/tests/test_saml_overlay.py` -- NEW; 9 integration tests + helpers + 2 fixtures + 1 session-autouse fixture-regeneration step

### Enterprise repo
- `geolens_enterprise/auth/saml/router.py` -- modernized imports; added correlation_id exception handler; added `?source=saml` redirect param; added ADFS URN attribute keys; added GET /metadata endpoint; added `_outstanding_requests` tracker
- `geolens_enterprise/auth/saml/config.py` -- modernized imports; added `accepted_time_diff: 60`; added `_strip_pem_headers()` helper applied to `_build_idp_metadata_xml`
- `geolens_enterprise/auth/saml/__init__.py` -- extended `EnterpriseSamlExtension` with no-op `resolve_identity_from_token`
- `geolens_enterprise/__init__.py` -- dual-registration of `saml_ext` under both `registry['auth']` and `registry['identity']`; helper rename `_get_auth_extension` -> `_get_saml_extension`
- `tests/test_registration.py` -- repaired stale `down_revision` assertion (Wave 1 fix); added 3 new tests
- `tests/test_saml_config.py` -- NEW; 4 tests
- `tests/test_replay_cache.py` -- NEW; 5 tests

## Decisions Made

- **Installed geolens-enterprise editable into the backend venv.** Required so the `saml_overlay_registered` conftest fixture can deferred-import the extension class and so `e002_add_saml_columns` runs at test-DB setup via the entry-point loader. Side effect: pysaml2's transitive dep on cryptography forced a momentary downgrade to 43.0.3, but `uv` re-resolved to the pinned 46.0.7 on next invocation. Verified versions.
- **Pre-set `version_locations` from entry-points before `command.upgrade`**, rather than relying on env.py to mutate the cfg post-construction. Discovered that `ScriptDirectory.from_config` caches `version_locations` at construction time, so an env.py-time mutation does NOT propagate to the upgrade walk. This was a real bug: enterprise branches would silently NOT run unless the conftest pre-sets the option. Switched `command.upgrade(..., "head")` -> `"heads"` (plural) for the same reason.
- **Patched `entry_points` to default-empty in the `test_extensions.py` autouse fixture.** With geolens-enterprise editable-installed, three pre-existing tests would otherwise fail (they assume an empty registry). Each test that needs extensions can opt-in via its own `with patch(...)`. Strict-improvement isolation; matches the test author's intent (registry isolation per test).
- **Added in-process `_outstanding_requests` dict to the SAML router.** Real fix to a real bug: without it, `allow_unsolicited=False` (D-15 hardening) rejects every response with "Unsolicited response: <reqid>" because there's no tracked queue. Single-process limitation matches ReplayCache; documented inline. This bug pre-dated this plan but only surfaced once integration tests exercised the full path.
- **Added `_strip_pem_headers()` helper.** Pre-existing scaffold bug: the `_build_idp_metadata_xml` function inlined the FULL PEM (including `-----BEGIN/END CERTIFICATE-----` markers) into the `<ds:X509Certificate>` element. xmlsec1 then fails to parse the resulting metadata file. Fix: strip headers + internal whitespace before inlining. Backwards-compatible: accepts already-stripped base64 body too.
- **Declared the 4 nullable SAML columns on the OAuthProvider ORM in core.** Plan 03 nominally owns this, but without it the SAML router cannot read `provider.idp_entity_id` etc. -- so Plan 02's tests cannot exercise the ACS path. Made minimal declaration only (4 nullable fields + relaxed CHECK literal); Pydantic schema validation + per-type discriminators land in Plan 03 unchanged.
- **Tests regenerate fixtures at session start.** SAML assertions have a default 15-minute validity window; fixtures committed last week would fail today. Session-autouse fixture re-runs `generate_fixtures.py` so timestamps stay fresh. The committed `.xml.b64` files are reproducibility snapshots, not the actual test inputs at runtime.
- **Per-test cleanup of SAML provider rows + JIT'd users.** The fixture's hardcoded Destination attribute (`/fixture/acs`) forces all ACS-POST tests to use slug `"fixture"`; cleanup means each test starts from a clean slate without violating the unique-slug or unique-email constraints.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stale test_enterprise_initial_migration_has_branch_label assertion**
- **Found during:** Task 02 (running enterprise tests after dual-registration changes)
- **Issue:** The test asserted `m.down_revision == "0010_add_saml_provider_columns"` but Wave 1 (Plan 01 a5cc4fe) repaired it to `f3a4b5c6d7e8`. The test was red on baseline.
- **Fix:** Updated assertion to the new revision; added docstring note explaining the Wave 1 repair.
- **Files modified:** `~/Code/geolens-enterprise/tests/test_registration.py`
- **Committed in:** `204c10c`

**2. [Rule 1 - Bug] _build_idp_metadata_xml inlined PEM with markers**
- **Found during:** Task 03 (test_saml_acs_signed_assertion_jit_provisions_user error: `xmlSecCryptoAppKeyLoadEx failed`)
- **Issue:** Pre-existing scaffold bug. The certificate PEM was passed verbatim into `<ds:X509Certificate>{certificate}</ds:X509Certificate>` -- but XMLDSig requires only the base64 DER body in that element (no PEM headers). pysaml2 then writes the cert to a temp file for xmlsec1, and xmlsec1 fails to parse it.
- **Fix:** Added `_strip_pem_headers()` helper. Strips `-----BEGIN/END ...-----` markers and internal whitespace. Idempotent for already-stripped input.
- **Files modified:** `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/config.py`
- **Committed in:** `d91db21`

**3. [Rule 1 - Bug] saml_acs called parse_authn_request_response without `outstanding`**
- **Found during:** Task 03 (test_saml_acs_signed_assertion_jit_provisions_user error: "Unsolicited response: id-fixture-request-001")
- **Issue:** Pre-existing scaffold bug. With `allow_unsolicited=False` (D-15 hardening default), pysaml2 rejects every response unless the InResponseTo matches a tracked outstanding request. The scaffold never tracked outstanding requests, so EVERY real response would be rejected. The bug only surfaced under integration testing.
- **Fix:** Added module-level `_outstanding_requests: dict[str, str]` populated by `saml_login()` (when it issues an AuthnRequest) and consumed by `saml_acs()` (passes it as `outstanding=` to pysaml2 + pops on success). Documented single-process limitation matching ReplayCache.
- **Files modified:** `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/router.py`
- **Committed in:** `d91db21`

**4. [Rule 3 - Blocker] OAuthProvider ORM model didn't declare SAML columns**
- **Found during:** Task 03 (writing the seed helper -- couldn't construct an OAuthProvider with `idp_entity_id` etc.)
- **Issue:** Plan 03 owns the formal Pydantic + service-layer extension, but the ORM model declaration is a strict prerequisite for Plan 02's tests. Without it, the router cannot read `provider.idp_entity_id` and tests cannot seed SAML provider rows via the ORM.
- **Fix:** Declared 4 nullable columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`) on `OAuthProvider`; relaxed the `chk_oauth_providers_type` literal to include `'saml'` (matches what e002 sets on the actual constraint). Minimal addition; Pydantic schema validation + service-layer per-type checks remain Plan 03 scope.
- **Files modified:** `backend/app/modules/auth/oauth/models.py`
- **Committed in:** `542fc38d`

**5. [Rule 3 - Blocker] conftest.py used "head" (singular) and didn't pre-set version_locations**
- **Found during:** Task 03 (e002 SAML columns missing in test DB even after enterprise installed)
- **Issue:** `command.upgrade(alembic_cfg, "head")` only walks one head; with the enterprise overlay installed, alembic has two heads (core + enterprise). Also: env.py mutates `version_locations` post-construction, but `ScriptDirectory` caches the value at construction time -- so the env.py mutation never propagates to the upgrade walk.
- **Fix:** Pre-set `version_locations` from the `geolens.migrations` entry-point group BEFORE calling `command.upgrade(...)`; switched the upgrade target from `"head"` to `"heads"` (plural). Backwards-compatible: with no enterprise installed, behaves identically to before (one head).
- **Files modified:** `backend/tests/conftest.py`
- **Committed in:** `542fc38d`

**6. [Rule 3 - Blocker] test_extensions.py tests fail with enterprise installed**
- **Found during:** Task 03 (running test_extensions.py after installing geolens-enterprise editable)
- **Issue:** Three baseline tests assume `_extensions` is empty after `load_extensions()`. With geolens-enterprise installed, `entry_points('geolens.extensions')` discovers the enterprise loader and populates the registry -- breaking these tests.
- **Fix:** Extended the autouse `_clean_registry` fixture to patch `app.platform.extensions.entry_points` to a default-empty list. Each test that needs extensions opts in via its own `with patch(...)`.
- **Files modified:** `backend/tests/test_extensions.py`
- **Committed in:** `542fc38d`

---

**Total deviations:** 6 auto-fixed (3 pre-existing scaffold bugs + 3 blocking infrastructure issues). All caught and fixed inline; none required architectural decisions or escalation.

**Impact on plan:** All deviations were necessary preconditions for the integration tests to run end-to-end. The three scaffold bugs (1, 2, 3 above) would have surfaced regardless of Phase 217 -- the existing scaffold could not actually process a real IdP response in production with `allow_unsolicited=False` and the cert-PEM bug. Plan 02 found and fixed them.

## Issues Encountered

- **Test fixture timestamps go stale:** SAML assertions have a default 15-minute validity window. Committed fixtures from Wave 1 fail wall-clock validation after 15 minutes. Mitigated by a session-autouse fixture that re-runs `generate_fixtures.py` at test start. Long-term: consider running CI's SAML test slice on a fresh container with the generator pre-run, or switch to `freezegun`-style time mocking. Not blocking; current approach works.
- **Cryptography downgrade on enterprise install:** Installing `geolens-enterprise` editable transitively requires pyOpenSSL which pulls cryptography back to 43.0.3, violating core's pinned `cryptography>=46.0.7`. `uv` self-resolves on next `uv run` to 46.0.7. Watch this if anyone does a manual `uv pip sync` against the backend venv -- the pin should win.
- **Module-level singleton state in tests:** The router's `_outstanding_requests` dict and `replay_cache._seen` dict are module-level globals. Test isolation is achieved by per-test clearing in `saml_router_mounted`. Multi-process pytest (e.g., `pytest-xdist`) would not work with these tests as-is; documented in fixture docstrings. Not blocking for Phase 217's single-process test runner.

## User Setup Required

None. All fixes are self-contained code/test changes; no env vars, secrets, or external services need configuration.

## Next Phase Readiness

- **Plan 03 (extend ORM/schemas/audit log)** can begin immediately. The 4 nullable SAML columns are already declared on the OAuthProvider ORM (Plan 02 did the minimal declaration); Plan 03 layers the Pydantic per-type validator on top. The `_seed_saml_provider` and `_load_fixture_b64` helpers in `test_saml_overlay.py` are ready to be reused by Plan 03's audit-log + role-mapping tests. Two more tests will be added to the same file: `test_saml_provider_update_logs_old_new_role_mapping` and `test_saml_attribute_to_role_mapping_via_provider_group_claim`.
- **Plan 04 (frontend admin UI + community 404 test)** can begin immediately. The router is mounted via the existing `_routers` discovery, gated by `require_enterprise()`; Plan 04's `test_saml_endpoint_404_in_community` will assert that without `saml_overlay_registered`, the routes return 404.
- **Plan 05 (docstring scrubs + verification gate)** can begin immediately.

## Self-Check: PASSED

Verified:
- `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/router.py` -- ast-parses; contains `create_metadata_string`, `?source=saml`, `correlation_id`, `http://schemas.microsoft.com/identity/claims/displayname`, `http://schemas.xmlsoap.org/claims/Group`; does NOT contain any `from app.auth.`/`from app.dependencies`/`from app.persistent_config`/`from app.public_urls`/`from app.extensions.guards` import; does NOT contain `quote(str(exc))`.
- `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/config.py` -- ast-parses; contains `accepted_time_diff`, `_strip_pem_headers`; uses modernized imports.
- `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/__init__.py` -- contains `async def resolve_identity_from_token`; does NOT inherit from any Protocol.
- `~/Code/geolens-enterprise/geolens_enterprise/__init__.py` -- contains `registry["identity"] = saml_ext`, `registry["auth"] = saml_ext`, and `_get_saml_extension`.
- `~/Code/geolens-enterprise/tests/test_registration.py` -- contains all 3 new test names; assertion updated to `f3a4b5c6d7e8`.
- `~/Code/geolens-enterprise/tests/test_saml_config.py` -- exists; 4 tests collected; all pass.
- `~/Code/geolens-enterprise/tests/test_replay_cache.py` -- exists; 5 tests collected; all pass.
- `backend/tests/test_saml_overlay.py` -- exists; 9 tests collected; all pass; contains the verbatim `_seed_saml_provider` (with placeholder `client_id="unused"` and `client_secret_encrypted=encrypt_secret("unused")` per checker WARNING #5) + `_load_fixture_b64` helpers.
- Full enterprise suite: 18 tests pass (`cd ~/Code/geolens-enterprise && uv run pytest`).
- SAML overlay suite: 9 tests pass (`cd backend && uv run pytest tests/test_saml_overlay.py`).
- Auth/OAuth/extensions/settings/SAML core surface (110 tests across test_auth.py, test_auth_refresh_logout.py, test_oauth.py, test_extensions.py, test_settings_oauth_crud.py, test_settings_router.py, test_saml_overlay.py): all green.
- Enterprise commits exist in `~/Code/geolens-enterprise` git log: `50a6ba3`, `204c10c`, `d91db21`.
- Core worktree commit exists: `542fc38d`.
- Dependency-presence grep: `xmlsec1` in `backend/Dockerfile`, `pysaml2` + `defusedxml` in `~/Code/geolens-enterprise/pyproject.toml`. OK.

---
*Phase: 217-auth-saml-enterprise*
*Completed: 2026-04-29*
