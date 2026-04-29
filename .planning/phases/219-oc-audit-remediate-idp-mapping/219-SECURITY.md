---
phase: 219
slug: oc-audit-remediate-idp-mapping
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-29
---

# Phase 219 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Community admin → `/settings/oauth-providers/` (POST/PATCH) | Admin with `manage_settings` writes OAuth provider config; payload crosses authenticated client → FastAPI route → Pydantic schema → DB write. The boundary the D-01 schema validator enforces. | OAuth provider config (`group_claim`, `group_role_mapping`, `default_role`) — sensitive: governs role assignment for SSO logins. |
| External IdP userinfo → `find_or_create_oauth_user()` | Userinfo dict (containing `groups` claim) crosses from OAuth callback into role-resolution logic at `service.py:265-270`. The boundary the D-05 service gate enforces. | IdP-asserted group membership claims — trust depends on edition; in community must be ignored. |
| Direct DB / migration scripts → `OAuthProvider` table | Any path that bypasses the schema layer (legacy data, direct SQL, Alembic data migrations). Defense-in-depth coverage from the D-05 service gate. | Pre-existing rows where `group_role_mapping` was set before the schema gate landed. |
| Edition singleton (`app.core.edition._info`) → `is_enterprise()` callers | Module-level state mutated by `init_edition()` at startup; read every request by validator + service gate. | Edition flag (boolean) — single-init at production startup; per-test isolation via D-10 autouse fixture. |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-219-01 | Elevation of Privilege | `OAuthProviderCreate` / `OAuthProviderUpdate` write path + `find_or_create_oauth_user` runtime path | mitigate | **Write path:** `_validate_idp_mapping_gate` `model_validator(mode="after")` on both schemas — `oauth/schemas.py:173-188` (Create) and `:285-300` (Update). Raises `ValueError("Group-based role mapping requires the GeoLens Enterprise overlay")` when `group_claim` set OR non-empty `group_role_mapping` AND `not is_enterprise()`. **Runtime path:** call site at `oauth/service.py:265-270` wraps `_resolve_role()` in `if is_enterprise():`; community uses `provider.default_role` regardless of legacy/direct-DB rows. | closed |
| T-219-02 | Tampering / regression | The boundary itself — future code change accidentally re-introduces unconditional group mapping (refactor moves `is_enterprise()` inside `_resolve_role`, schema validator deletion, etc.) | mitigate | **Unit-level:** `TestIdpRoleMappingGate` 6/6 PASS + 2 runtime split tests fail loudly if either gate is removed. **Structural-level:** `/oc-audit` re-run flags any 🔴 regression under OAuth IdP cluster — Boundary Integrity grade reflects gate presence. **Doc-level:** `docs-internal/audits/oc-separation-audit-v13.1-close.md` cites validator name (`_validate_idp_mapping_gate`) and call site (`service.py:265-270`) — future readers can grep to verify wiring intact. | closed |
| T-219-03 | Information Disclosure (low) | A community admin attempting to write `group_role_mapping` may infer from the verbatim error string ("requires the GeoLens Enterprise overlay") that an enterprise tier exists. | accept | Intentional GTM messaging — error names the upgrade path, matching the convention at `app/platform/extensions/guards.py` and `app/modules/audit/router.py`'s `require_enterprise()` 404 contract. No PII or system-internal details revealed. Surfaces only to authenticated admins with `manage_settings`; the "knows enterprise exists" signal is public marketing-page information. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-219-01 | T-219-03 | Verbatim "requires the GeoLens Enterprise overlay" error message is intentional GTM signaling. The information leaked ("an enterprise tier exists") is identical to public marketing surface. Restricted to authenticated admins with `manage_settings` — same audience that already sees enterprise-gated UI affordances. Matches established convention at `guards.py` and `audit/router.py` `require_enterprise()` 404 contract. Per-CONTEXT.md D-03. | Phase 219 plan author / orchestrator | 2026-04-29 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-29 | 3 | 3 | 0 | Claude (gsd-secure-phase, retroactive State-B run from PLAN+SUMMARY artifacts) |

### Audit 2026-04-29 — verification details

**Method:** Retroactive State-B run. No SECURITY.md existed pre-audit; threat register reconstructed from `<threat_model>` block in `219-01-PLAN.md` (lines 1140-1157) and `## Threat Flags` in `219-01-SUMMARY.md`. Each threat verified against current `main` codebase via grep + code read.

**T-219-01 verification:**
- `grep -n "_validate_idp_mapping_gate\|Group-based role mapping" backend/app/modules/auth/oauth/schemas.py` → 6 matches confirming validator wired on both Create (line 173) and Update (line 285), each with verbatim error string raised twice (lines 184/188 and 296/300).
- `grep -n "is_enterprise\|default_role" backend/app/modules/auth/oauth/service.py` → confirms `if is_enterprise():` at line 265 with community fallback `role_name = provider.default_role` at line 270.
- `cd backend && uv run pytest tests/test_oauth.py::TestIdpRoleMappingGate -v` → **6 passed in 1.33s**.

**T-219-02 verification:**
- Unit-level: `TestIdpRoleMappingGate` 6/6 PASS — regression of either gate would flip these to FAIL.
- Structural-level: `oc-separation-audit-v13.1-close.md:9` records Boundary Integrity grade **A** (post-Phase-219, exceeds A− target). Section 1 OAuth IdP rows (lines 68-70) all 🟢 with `Closed by Phase 219, 2026-04-29` annotations. Section 8 grade-delta (line 387): `Boundary Integrity | B | B− | A | ↑ | A− | ✅ YES`.
- Doc-level: validator name + call site explicitly cited in audit doc (lines 9, 70 cite `oauth/schemas.py:174-190, 286-300` and `oauth/service.py:265-270`).

**T-219-03 verification:**
- Documented as `accept` disposition in PLAN.md line 1156 with rationale.
- Pattern matches `require_enterprise()` 404 contract at `app/modules/audit/router.py` and guards at `app/platform/extensions/guards.py` — both already shipping the same "enterprise overlay" signal.
- Recorded in Accepted Risks Log as AR-219-01.

**No new threats discovered during retroactive audit.** Phase 219's scope (RESTRICT existing surface) is inherently surface-reducing — no new attack vectors introduced.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-29
