---
phase: 217
slug: auth-saml-enterprise
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-29
---

# Phase 217 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x with pytest-asyncio (existing project standard) |
| **Config file** | `backend/pyproject.toml` `[tool.pytest.ini_options]` (existing) |
| **Quick run command** | `cd backend && uv run pytest tests/test_saml_overlay.py -x` (after Wave 0 file creation) |
| **Full suite command** | `cd backend && uv run pytest -x` (existing 2001-test baseline + new SAML tests) |
| **Estimated runtime** | ~30s for SAML suite alone; ~6 min for full backend suite |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && uv run pytest tests/test_saml_overlay.py -x`
- **After every plan wave:** Run `cd backend && uv run pytest -x`
- **Before `/gsd-verify-work`:** Full suite must be green AND `cd backend && uv run alembic check` clean AND `cd ~/Code/geolens-enterprise && uv run pytest -x` clean
- **Max feedback latency:** 30 seconds (SAML suite)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 217-01-01 | 01 | 1 | (alembic repair) | — | `e001` chains off `f3a4b5c6d7e8` | unit | `cd ~/Code/geolens-enterprise && uv run python -c "from geolens_enterprise.migrations.versions.e001_enterprise_initial import down_revision; assert down_revision == 'f3a4b5c6d7e8'"` | ❌ W0 | ⬜ pending |
| 217-01-02 | 01 | 1 | SAML-08, SAML-09 | — | `e002_add_saml_columns` runs cleanly on top of core HEAD | integration | `cd backend && uv run alembic check` (after applying enterprise overlay) | ❌ W0 | ⬜ pending |
| 217-02-01 | 02 | 2 | SAML-09 | — | EnterpriseSamlExtension implements both AuthExtension and IdentityExtension | unit | `cd backend && uv run pytest tests/test_saml_overlay.py::test_saml_overlay_registers_under_identity_and_routers -x` | ❌ W0 | ⬜ pending |
| 217-02-02 | 02 | 2 | SAML-11 | XSW (T-217-XSW), Replay (T-217-REPLAY), Clock skew (T-217-SKEW), AudienceRestriction bypass (T-217-AUD) | Signed assertion validation; replay cache; AudienceRestriction enforced | integration | `cd backend && uv run pytest tests/test_saml_overlay.py::test_saml_acs_signed_assertion_jit_provisions_user tests/test_saml_overlay.py::test_saml_acs_rejects_invalid_signature tests/test_saml_overlay.py::test_saml_acs_rejects_expired_assertion tests/test_saml_overlay.py::test_saml_acs_rejects_replayed_assertion -x` | ❌ W0 | ⬜ pending |
| 217-02-03 | 02 | 2 | SAML-11 | — | Metadata XML endpoint returns valid samlmetadata+xml | integration | `cd backend && uv run pytest tests/test_saml_overlay.py::test_saml_metadata_xml_valid -x` | ❌ W0 | ⬜ pending |
| 217-03-01 | 03 | 3 | SAML-12 | Credential leak in audit log (T-217-AUDIT-LEAK) | Audit log captures old/new role mapping diff; `idp_certificate` redacted | integration | `cd backend && uv run pytest tests/test_saml_overlay.py::test_saml_provider_update_logs_old_new_role_mapping tests/test_saml_overlay.py::test_saml_provider_update_redacts_secret_fields -x` | ❌ W0 | ⬜ pending |
| 217-03-02 | 03 | 3 | SAML-12 | — | Attribute → role mapping configurable via group_claim/group_role_mapping | integration | `cd backend && uv run pytest tests/test_saml_overlay.py::test_saml_attribute_to_role_mapping_via_provider_group_claim -x` | ❌ W0 | ⬜ pending |
| 217-04-01 | 04 | 4 | SAML-10 | — | `/auth/saml/providers` returns 404 in community (no overlay loaded) | integration | `cd backend && uv run pytest tests/test_saml_overlay.py::test_saml_endpoint_404_in_community -x` | ❌ W0 | ⬜ pending |
| 217-04-02 | 04 | 4 | SAML-10 | — | Frontend admin sidebar hides SAML nav item when `useEdition()` returns community | unit | `cd frontend && npm run test -- AdminSidebar.test.tsx` | ❌ W0 | ⬜ pending |
| 217-05-01 | 05 | 5 | SAML-08 | — | `git grep -i saml` against core (with carve-outs) returns zero hits | shell | `git grep -i saml backend/ ':!backend/alembic/' ':!backend/tests/fixtures/saml/' ':!backend/tests/test_saml_overlay.py'` (expects empty) | ❌ W0 | ⬜ pending |
| 217-05-02 | 05 | 5 | (verification gate) | — | Full backend pytest baseline preserved | integration | `cd backend && uv run pytest -x` (must keep 2001-test baseline green plus new SAML tests) | ✅ existing | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/fixtures/saml/idp_cert.pem` + `idp_key.pem` — fixture IdP signing keypair (openssl-generated; checked in)
- [ ] `backend/tests/fixtures/saml/idp_response_signed.xml.b64` — pre-signed SAML response from a known fixture IdP (use pysaml2 IdP simulator to generate once, commit)
- [ ] `backend/tests/fixtures/saml/idp_response_expired.xml.b64` — same content with NotOnOrAfter in the past (for expiry test)
- [ ] `backend/tests/fixtures/saml/idp_response_xsw.xml.b64` — XSW attack fixture (signed wrapped inside unsigned `<Object>` — must trigger SignatureError per Pitfall 2)
- [ ] `backend/tests/fixtures/saml/idp_response_unsigned.xml.b64` — unsigned response (must trigger validation failure)
- [ ] `backend/tests/fixtures/saml/idp_response_replay.xml.b64` — second submission of same assertion (replay cache must reject)
- [ ] `backend/tests/test_saml_overlay.py` — covers SAML-08..12 (10 tests as listed in §12 of RESEARCH.md)
- [ ] `backend/tests/conftest.py` extension: helper fixture `saml_overlay_registered` that programmatically inserts `EnterpriseSamlExtension()` into `app.platform.extensions._extensions` for the duration of the test
- [ ] `~/Code/geolens-enterprise/tests/test_saml_config.py` — covers `build_saml_client()` and `_build_idp_metadata_xml()` in isolation
- [ ] `~/Code/geolens-enterprise/tests/test_replay_cache.py` — covers `ReplayCache` TTL behavior

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real IdP round-trip (e.g., Okta or SimpleSAMLphp) | SAML-11 | Requires live IdP environment; not reproducible in CI | Set up SimpleSAMLphp Docker; configure provider in admin UI; click login; confirm SSO completes and JWT is issued |
| Admin SAML nav item invisibility in community Docker compose | SAML-10 | Frontend integration test; needs full bundle + backend running | Start `docker compose up` (without enterprise overlay); log in as admin; verify no SAML nav item; navigate directly to `/admin/saml` and confirm 404 |
| SP metadata XML validity in real IdP import | SAML-11 | Requires real IdP's metadata-import flow | Fetch `/auth/saml/{slug}/metadata`; import into target IdP (Okta/Azure AD/ADFS); confirm IdP accepts SP descriptor without error |
| Browser back-button replay safety | (Pitfall 6) | Requires browser; not reproducible in headless CI | Complete SAML login; click browser back; confirm no re-POST and no error |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s (SAML suite)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
