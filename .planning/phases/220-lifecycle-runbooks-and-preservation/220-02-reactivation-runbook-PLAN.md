---
phase: 220-lifecycle-runbooks-and-preservation
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - docs/edition-reactivation.md
autonomous: true
requirements:
  - LIFECYCLE-02

must_haves:
  truths:
    - "Operator can read docs/edition-reactivation.md and execute the community→enterprise re-upgrade end-to-end"
    - "Runbook confirms (with verifiable post-reactivation checks) that deferred=True SAML columns and oauth_providers SAML rows survive deactivation and are usable immediately on re-mount"
    - "Runbook is thin (~½ page) and links to existing activation steps in docs/saml.md rather than re-walking the activation sequence (per RESEARCH.md A3)"
    - "Runbook cross-links to docs/edition-deactivation.md (lifecycle navigability per D-07)"
  artifacts:
    - path: "docs/edition-reactivation.md"
      provides: "Operator reactivation runbook + post-reactivation verification checklist (LIFECYCLE-02)"
      contains:
        - "verify"
        - "/auth/saml"
        - "edition-deactivation"
        - "oauth_providers"
        - "deferred"
  key_links:
    - from: "docs/edition-reactivation.md"
      to: "docs/edition-deactivation.md"
      via: "markdown link"
      pattern: "edition-deactivation"
    - from: "docs/edition-reactivation.md"
      to: "docs/saml.md"
      via: "markdown link (activation reference)"
      pattern: "\\(saml\\.md\\)"
---

<objective>
Author docs/edition-reactivation.md — the operator runbook for the community→enterprise re-upgrade. Per RESEARCH.md A3 + CONTEXT.md Claude's Discretion: this runbook is **thin** (~½ page). It does not re-walk the activation sequence (saml.md already covers that); it focuses on the post-reactivation verification checklist that proves `deferred=True` SAML columns and `oauth_providers` rows survived the deactivation period and are usable.

Purpose: Close LIFECYCLE-02 — give operators a verifiable confirmation procedure for re-upgrade so the round-trip is a documented operation, not folklore.

Output: New top-level doc docs/edition-reactivation.md (no docs/lifecycle/ subdir per D-07).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/phases/220-lifecycle-runbooks-and-preservation/220-CONTEXT.md
@.planning/phases/220-lifecycle-runbooks-and-preservation/220-RESEARCH.md
@.planning/phases/220-lifecycle-runbooks-and-preservation/220-PATTERNS.md
@.planning/phases/220-lifecycle-runbooks-and-preservation/220-VALIDATION.md
@docs/saml.md

<style_anchor>
Anchor on docs/saml.md Installation section (saml.md:32-58) — that's the existing community→enterprise activation walkthrough this doc complements. Do NOT duplicate it; link to it. Tone: ATX headings, ```bash``` blocks, `>` blockquote callouts with bold lead, concise lists.
</style_anchor>

<verify_excerpts>
Post-reactivation verification commands the runbook prescribes (operators copy/paste these):

```bash
# 1. SAML routes mounted
curl -fsS http://localhost:8000/openapi.json | jq '.paths | keys[] | select(test("/auth/saml/"))'
# Expected: list of SAML routes (metadata, login, acs, etc.)

# 2. Enterprise overlay loaded
docker compose logs api | grep -i 'loaded extension' | head -5
# Expected: "loaded extension: identity" / "loaded extension: auth" / "loaded extension: audit" / "loaded extension: branding"

# 3. SAML providers visible in admin UI: navigate to admin → SAML SSO tab → confirm pre-deactivation providers re-appear

# 4. Schema confirmation (the 4 deferred columns are physically present and queryable)
PGPASSWORD=<pw> psql -h <host> -U <user> -d <db> -c "
  SELECT column_name FROM information_schema.columns
  WHERE table_schema='catalog' AND table_name='oauth_providers'
    AND column_name IN ('idp_entity_id','idp_sso_url','idp_certificate','sp_entity_id');
"
# Expected: 4 rows.

# 5. SAML rows survive
PGPASSWORD=<pw> psql -h <host> -U <user> -d <db> -c "
  SELECT count(*) FROM catalog.oauth_providers WHERE provider_type='saml';
"
# Expected: same count as pre-deactivation snapshot.
```
</verify_excerpts>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Author docs/edition-reactivation.md (thin runbook focused on post-reactivation verification)</name>
  <files>docs/edition-reactivation.md</files>
  <read_first>
    - docs/saml.md (style anchor + activation reference; saml.md:32-58 is the activation walkthrough this doc links to)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-CONTEXT.md (D-07 — top-level docs/, D-01 mechanical lifecycle context)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-RESEARCH.md (A3 — recommend thin runbook; "Validation Architecture" — verification command shapes)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-PATTERNS.md (operator-doc tone shared pattern; verification-by-grep discipline)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-VALIDATION.md (LIFECYCLE-02 grep block)
    - backend/app/modules/auth/oauth/models.py (lines 67-78 — `deferred=True, deferred_group="saml"` declaration the verify section references)
  </read_first>
  <action>
Create docs/edition-reactivation.md with the following sections. The doc MUST be thin (~½ page; ~50-100 lines max). Implements LIFECYCLE-02. Uses ATX headings, ```bash``` for shell, ```sql``` for SQL.

REQUIRED LITERAL STRINGS (VALIDATION.md greps):
- "verify" or "verification" (case-insensitive — both work; use both naturally)
- "/auth/saml" (verbatim — appears in the curl verify command)
- "edition-deactivation" (verbatim — cross-link target)
- "oauth_providers" (verbatim — appears in schema verify SQL)
- "deferred" (verbatim — explains the column-physical-presence guarantee)

SECTION-BY-SECTION SPEC:

1. **Title + audience callout (mirror saml.md:1-3):**
   ```markdown
   # Edition Reactivation: Community → Enterprise

   > **This runbook is for operators re-upgrading a previously deactivated GeoLens deployment back to enterprise edition.** If you are activating enterprise for the first time, see [`docs/saml.md`](saml.md) — Installation section instead.
   ```

2. **One-paragraph orientation** (3-4 sentences). Explains: "Re-upgrade is structurally the inverse of deactivation. If you followed the safe path in [`docs/edition-deactivation.md`](edition-deactivation.md), your `oauth_providers` SAML rows and the 4 `deferred=True` SAML columns are still in the database — re-mounting the overlay makes them queryable again. No data restore, no migration replay, no admin re-configuration."

3. **`## Re-mount the overlay`** — short walkthrough (3-5 lines). Link to saml.md Installation as the canonical activation reference; include only the minimum operator-facing commands here:
   ```bash
   # Stop community-only stack
   docker compose down

   # Bring up the enterprise stack (loads geolens-enterprise + ensures e002 is at head)
   docker compose -f docker-compose.yml -f docker-compose.enterprise.yml up -d --build

   # Migrations run automatically on container start; if needed manually:
   docker compose exec api uv run alembic upgrade heads
   ```
   Follow with: "For full activation context (IdP setup, admin UI walkthrough, hardening defaults), see [`docs/saml.md`](saml.md) — Installation section."

4. **`## Post-reactivation verification checklist`** — numbered list of 5 verifiable checks. Each item is a ```bash``` or ```sql``` block + an "Expected: ..." line. Use the verbatim commands from `<verify_excerpts>` above:

   1. **SAML routes mounted.** Use the `/auth/saml` curl command from `<verify_excerpts>`. Expected: list of SAML routes.
   2. **Enterprise overlay loaded.** Use the `docker compose logs api | grep -i 'loaded extension'` command from `<verify_excerpts>`. Expected: 4 lines (auth, identity, audit, branding).
   3. **Pre-deactivation SAML providers re-appear in the admin UI.** Sign in to admin → **SAML SSO** tab → confirm the same `slug`, `display_name`, and `enabled` state as the pre-deactivation snapshot.
   4. **Schema confirmation — the 4 `deferred=True` columns are physically present.** Use the `information_schema.columns` SQL from `<verify_excerpts>`. Expected: 4 rows.
   5. **SAML provider row count matches pre-deactivation snapshot.** Use the `count(*)` SQL from `<verify_excerpts>`. Expected: same count as pre-deactivation snapshot (compare against the `pg_dump` snapshot taken in the deactivation runbook's pre-flight).

5. **`## End-to-end smoke test`** — single short bullet:
   - Open a private browser window, navigate to `/login`, click a SAML provider button, complete the IdP round-trip, confirm you land back in GeoLens authenticated. If the IdP rejects with `Unsolicited response` for outstanding-request reasons, the user retries — pending-request state was cleared during deactivation; new logins re-establish it.

6. **`## Why this works`** — 2-3 sentences citing the architectural mechanism:
   "The 4 SAML columns on `catalog.oauth_providers` are added by `e002_add_saml_columns` (the enterprise alembic head). The ORM declares them `deferred=True, deferred_group="saml"` — when the overlay is absent, default queries never load them, so community deployments work unchanged. The columns and rows persist physically regardless of whether the overlay is loaded; re-mounting only restores the consumer (the SAML router and admin UI) of pre-existing data."

7. **`## References`** (mirror saml.md:217-223 — backtick + em-dash):
   ```markdown
   - [`docs/edition-deactivation.md`](edition-deactivation.md) — the inverse procedure; pre-flight pg_dump snapshot is the safety net referenced in step 5 of the verification checklist.
   - [`docs/saml.md`](saml.md) — SAML setup, IdP configuration, hardening defaults.
   ```

DO NOT include emojis. DO NOT add a re-walk of the saml.md activation sequence (link, don't duplicate). Keep the file under ~100 lines.
  </action>
  <verify>
    <automated>
test -f docs/edition-reactivation.md && \
grep -q -i 'verify\|verification' docs/edition-reactivation.md && \
grep -q '/auth/saml' docs/edition-reactivation.md && \
grep -q 'edition-deactivation' docs/edition-reactivation.md && \
grep -q 'oauth_providers' docs/edition-reactivation.md && \
grep -q 'deferred' docs/edition-reactivation.md && \
[ "$(wc -l &lt; docs/edition-reactivation.md)" -le 120 ]
    </automated>
  </verify>
  <acceptance_criteria>
    - File `docs/edition-reactivation.md` exists.
    - File contains either `verify` or `verification` (case-insensitive).
    - File contains the literal string `/auth/saml` (used in the route-verify curl).
    - File contains the literal string `edition-deactivation` (cross-link to deactivation runbook).
    - File contains the literal string `oauth_providers` (DB identifier in the schema verify SQL).
    - File contains the literal string `deferred` (explains the column-physical-presence guarantee).
    - File line count is ≤ 120 lines (thin runbook per RESEARCH.md A3 — generous upper bound to allow for code blocks).
    - File does NOT re-walk the saml.md Installation section (it links to it via `[saml.md](saml.md)` reference).
    - File does NOT contain emojis.
  </acceptance_criteria>
  <done>docs/edition-reactivation.md is a thin (~½ page) runbook satisfying LIFECYCLE-02 with a verifiable 5-step post-reactivation checklist that proves `deferred=True` columns and `oauth_providers` rows survive a deactivation period. All grep + line-count assertions in &lt;automated&gt; pass.</done>
</task>

</tasks>

<verification>
- All grep assertions pass.
- Line count ≤ 120 confirms thin-runbook discipline.
- Cross-links resolve when rendered in GitHub markdown preview.
</verification>

<success_criteria>
- LIFECYCLE-02 satisfied: operator-facing reactivation walkthrough + verifiable confirmation that deferred=True SAML columns + oauth_providers rows are intact and usable on re-upgrade.
- D-07 honored: top-level docs/ placement.
- A3 honored: thin runbook; activation reference goes through saml.md, not duplicated.
</success_criteria>

<output>
After completion, create `.planning/phases/220-lifecycle-runbooks-and-preservation/220-02-SUMMARY.md` capturing: file path, line count, list of verifiable checks the doc prescribes, any deviations from this plan with rationale.
</output>
