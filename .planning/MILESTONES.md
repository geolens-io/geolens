# Milestones

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
3. **Auto-generated SDKs shipped** — Python (`pip install geolens-sdk`) + TypeScript (`@geolens/sdk`) clients regenerate from `backend/openapi.json` one-shot via `make sdks`; `make sdks-check` CI gate prevents drift; `flatten_openapi_defs.py` preprocessor resolves OpenAPI 3.1 inline `$defs` (Phase 215).
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
