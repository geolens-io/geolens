# Milestones

## v13.2 Edition Lifecycle Hardening (Shipped: 2026-04-30)

**Milestone goal:** Close the deactivation/reactivation lifecycle gap surfaced during v13.1 close-out — make enterprise→community downgrade safe and re-upgrade lossless before any paying customer hits these gaps.

**Stats:**

- **Phases:** 2 (220, 221)
- **Plans:** 9 / 9 complete (6 in 220, 3 in 221)
- **Timeline:** 2026-04-29 → 2026-04-30 (2 days)
- **Commits:** 58 in milestone range (`192fe7e1..a0758e99`)
- **Diff:** 80 files, +12,308 / -439 (incl. SDK regen + format pass)

**Requirements:** 7/7 satisfied (LIFECYCLE-01..07)

**Key accomplishments:**

1. **Operator runbooks for the full lifecycle** — `docs/edition-deactivation.md` (186 lines, 10 sections) for enterprise→community downgrade and `docs/edition-reactivation.md` for the re-upgrade. `docs/saml.md` no longer presents `alembic downgrade -1` as the primary path; it now cross-links to the new runbook and labels the destructive path as opt-in with a mandatory `pg_dump` pre-step (Phase 220, LIFECYCLE-01/02/03/05).
2. **SAML data preservation verified by integration test** — `backend/tests/test_lifecycle.py::test_overlay_removal_preserves_saml_data` confirms `oauth_providers` rows + 4 `deferred=True` SAML columns + `oauth_accounts` linkages survive a registry-clear deactivation. The `lifecycle` pytest marker is registered in `backend/pyproject.toml` and runs by default in CI when the geolens-enterprise overlay is installed (Phase 220, LIFECYCLE-04).
3. **CI overlay install with graceful fork-PR fallback** — `.github/workflows/ci.yml` conditionally checks out and installs `geolens-enterprise` based on `GEOLENS_ENTERPRISE_TOKEN` secret presence; pytest runs with lifecycle marker INCLUDED when overlay available, deselected on fork PRs without secret. No fork-PR breakage (Phase 220, LIFECYCLE-04 CI side).
4. **Admin SAML→local conversion endpoint** — `POST /admin/users/{user_id}/convert-saml-to-local/` (audit action `user.convert_saml_to_local`) flips a SAML user to local-password in a single transaction, preserving `users.id` (every FK referencing it stays intact) and deleting only the SAML `oauth_accounts` linkage. Self-conversion blocked with 422 (Phase 221, LIFECYCLE-06).
5. **Round-trip symmetry guaranteed** — `test_deactivate_reactivate_roundtrip_preserves_saml_data` drives the registry through a full deactivate → reactivate cycle and asserts losslessness across the 4 deferred SAML columns + `oauth_accounts` linkage + User row + a seeded `audit_log` row (Phase 221, LIFECYCLE-07).
6. **Post-impl audit + tech-debt close in same milestone** — Post-impl audit ran 2026-04-30 (`docs-internal/audits/post-impl-20260430.md`): 47 findings → 20 fixed across 5 commits (P1 resilience: GDAL info-leak sanitization, Titiler timeout, RegisterForm fieldset, embedding dim guard; admin module helper consolidation; schema tightening; frontend polish; logging). Plus 2 pre-existing phase-217 test failures fixed (`test_saml_provider_update_logs_old_new_role_mapping` missing fixture; `test_collections::test_update_collection` `MissingGreenlet` cascade across 974+ tests). Final: 2036/2036 backend tests green at 62.29% coverage; 1009 frontend tests green.

**Known deferred items at close:** 172 (see STATE.md `## Deferred Items`)

- 170 cross-milestone `quick_tasks` (carried over from v13.1; hygiene debt)
- 1 UAT gap (Phase 220 UAT-2 — lifecycle CI literal log line confirmation; local equivalent verified, CI blocked on Actions free-tier billing through 2026-04-30; reset 2026-05-01)
- 1 verification gap (Phase 220 — same UAT-2 item)

**Known gaps:** None at functional level. v13.2-MILESTONE-AUDIT.md graded `tech_debt`; all 5 tech-debt items closed inline same day (audit-action rename `auth.*` → `user.*`, frontmatter backfill, validation status flips). Local CI-equivalent gates all green at close: ruff + format + openapi snapshot + sdks drift + bandit + pytest with lifecycle marker INCLUDED + frontend lint/tsc/vitest.

**Tag:** `v13.2`

---

## v13.1 Open-Core Separation P1 (Shipped: 2026-04-29)

**Milestone goal:** Close the six P1 boundary/seam debts surfaced in the open-core audit so the open-core architecture is demonstrably ship-ready before the first paid customer. Target audit grade improvements: Boundary B → A−, Seam Quality C → B, OSS Surface D → C.

**Stats:**

- **Phases:** 8 (212 → 219; Phase 219 added mid-milestone to close P0 surfaced by Phase 218)
- **Plans:** 30 / 30 complete
- **Timeline:** 2026-04-26 → 2026-04-29 (4 days)
- **Commits:** 179 in milestone range
- **Diff:** 903 files, +163,458 / -479
  - Hand-written: 125 files, +10,143 / -413
  - Generated SDK code: 655 files, +112,074 (Python + TypeScript clients from OpenAPI)
  - Planning artifacts: 123 files, +41,241

**Audit grades (vs targets):**

| Dimension | Target | Result | Met? |
|-----------|--------|--------|------|
| Boundary Integrity | A− | A | ✅ exceeds |
| Seam Quality | B | B | ✅ |
| OSS Surface Readiness | C | A− | ✅ exceeds |

**Requirements:** 21/21 satisfied (LAYER-01..02, IDENT-01..03, OCSDK-01..04, OCCLI-01..06, SAML-08..12, AUDIT-V1)

**Key accomplishments:**

1. **Open-core boundary closed** — `core/` no longer imports from `modules/settings/`; `auth/visibility.py` relocated to `catalog/authorization.py` with all 23 inbound callers migrated; broadened architecture-guard test prevents regression (Phases 212, 213).
2. **IdentityProtocol extracted** — 51 cross-domain `User` import sites retyped to `Identity` Protocol; extension hook (`get_identity_extension()`) lets enterprise overlays register custom identity backends without core changes; 18-file allowlist guard enforces invariant (Phase 214).
3. **Auto-generated SDKs shipped** — Python (`pip install geolens`) + TypeScript (`@geolens/sdk`) clients regenerate from `backend/openapi.json` one-shot via `make sdks`; `make sdks-check` CI gate prevents drift; `flatten_openapi_defs.py` preprocessor resolves OpenAPI 3.1 inline `$defs` (Phase 215).
4. **`geolens` CLI MVP on PyPI** — Apache-2.0 standalone CLI (`login` keyring + headless / `scan` / `publish` / `export stac`) consuming only the generated Python SDK; zero hand-rolled HTTP imports enforced by CI grep + tomllib gates; 112 unit tests + 6 round-trip tests pass (Phase 216).
5. **SAML enterprise overlay** — `geolens-enterprise` registers via `importlib.metadata` entry_points with dual `AuthExtension` + `IdentityExtension` Protocol seams; SP-initiated SSO + JIT provisioning via existing `find_or_create_oauth_user()` + audited attribute→role mapping; admin UI 3-layer gated (`useEdition()` + sidebar filter + backend 404); SAML scaffold in core limited to documented Pitfall 11 mitigation (deferred=True ORM columns) (Phase 217).
6. **Audit gate met** — Closing audit produced at `docs-internal/audits/oc-separation-audit-v13.1-close.md` (Phase 218); OAuth IdP→role mapping P0 surfaced by audit closed by Phase 219 via `is_enterprise()` gate at schema validator + service path; audit document amended in place from BLOCKED → VERIFIED (Phase 219).

**Known deferred items at close:** 175 (see STATE.md `## Deferred Items`)

- 170 cross-cutting `quick_tasks` from earlier milestones (hygiene debt, not v13.1-specific)
- 1 UAT gap on Phase 216 (4 documented `human_needed` items: PyPI publish, OS keyring per-platform, interactive Progress UI, refresh-token retry)
- 4 verification gaps (215/216 `human_needed`; 999.2/999.4 P3 backlog)

**Known gaps:** None at functional level. v13.1-MILESTONE-AUDIT.md graded `tech_debt` due to paperwork lag (missing phase-level VERIFICATION.md × 4, draft VALIDATION.md × 6, REQUIREMENTS.md checkbox lag); all closed via paperwork pass at commit `5dfc1f8c` (2026-04-29).

**Tag:** `v13.1`

---
