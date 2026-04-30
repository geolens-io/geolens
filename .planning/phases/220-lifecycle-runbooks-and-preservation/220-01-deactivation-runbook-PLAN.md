---
phase: 220-lifecycle-runbooks-and-preservation
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - docs/edition-deactivation.md
autonomous: true
requirements:
  - LIFECYCLE-01
  - LIFECYCLE-05

must_haves:
  truths:
    - "Operator can read docs/edition-deactivation.md and execute the safe enterprise→community downgrade end-to-end without external help"
    - "Runbook prescribes overlay-removal as the canonical lever (per D-01) and labels GEOLENS_EDITION=community as defense-in-depth, NOT as the primary switch"
    - "Runbook documents the alembic downgrade -1 path as destructive/opt-in with a mandatory pg_dump pre-step (per D-02), enumerating the rows deleted: oauth_accounts SAML rows, oauth_providers SAML rows, and the 4 SAML columns dropped"
    - "Runbook contains a data-fate matrix mapping data class × scenario (safe path / destructive path) for oauth_providers SAML rows, oauth_accounts SAML rows, users with auth_provider='oauth', and audit log entries"
    - "Runbook cross-links to docs/edition-reactivation.md and docs/saml.md (per D-07) so the lifecycle is navigable"
  artifacts:
    - path: "docs/edition-deactivation.md"
      provides: "Canonical operator deactivation runbook (LIFECYCLE-01, LIFECYCLE-05)"
      contains:
        - "pre-flight"
        - "pg_dump"
        - "oauth_providers"
        - "docker compose down"
        - "GEOLENS_EDITION"
        - "defense-in-depth"
        - "destructive"
        - "edition-reactivation.md"
        - "saml.md"
        - "data-fate"
  key_links:
    - from: "docs/edition-deactivation.md"
      to: "docs/edition-reactivation.md"
      via: "markdown link"
      pattern: "edition-reactivation"
    - from: "docs/edition-deactivation.md"
      to: "docs/saml.md"
      via: "markdown link (IdP-side cleanup)"
      pattern: "\\(saml\\.md\\)"
---

<objective>
Author docs/edition-deactivation.md — the authoritative operator runbook for the enterprise→community downgrade. This is the canonical artifact LIFECYCLE-03's saml.md cross-link points at, so it must exist and contain the full pre-flight → stop overlay → verify sequence, plus the data-fate matrix and the destructive-path callout that satisfies LIFECYCLE-05.

Purpose: Replace the existing "alembic downgrade -1 is reversible, back up first" mental model in saml.md with a complete operator-facing lifecycle doc that prescribes overlay-removal first and documents the destructive alembic path with a mandatory pg_dump pre-step.

Output: New top-level doc docs/edition-deactivation.md (no docs/lifecycle/ subdir per D-07).
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
docs/saml.md is the ONLY substantive operator doc remaining in this repo (per RESEARCH.md Pitfall 1; all other docs/*.md are 3-line redirect stubs to docs.getgeolens.com). Anchor tone, heading depth, code-block style, blockquote-callout shape, and table shape on saml.md. Do NOT cite docs/upgrade-guide.md, docs/install-guide.md, docs/admin-guide.md, docs/cloud-deployment.md, or docs/configuration-reference.md as style references — they are stubs.
</style_anchor>

<command_excerpts>
From backend/scripts/api-entrypoint.sh:46-58 (the runtime overlay install conditional the runbook quotes):
```bash
if [ -d "${ENTERPRISE_PATH}" ] && [ -f "${ENTERPRISE_PATH}/pyproject.toml" ]; then
    uv add --editable "${ENTERPRISE_PATH}"
fi
```

From ~/Code/geolens-enterprise/geolens_enterprise/migrations/versions/e002_add_saml_columns.py downgrade() — destructive-path enumeration (verbatim order, per RESEARCH.md Pitfall 4):
1. DELETE FROM catalog.oauth_accounts WHERE provider_id IN (SELECT id FROM catalog.oauth_providers WHERE provider_type = 'saml')
2. DELETE FROM catalog.oauth_providers WHERE provider_type = 'saml'
3. op.drop_constraint("chk_oauth_providers_type", ...)
4. op.create_check_constraint("chk_oauth_providers_type", ..., "provider_type IN ('oidc', 'google', 'microsoft')")
5. op.drop_column("oauth_providers", "sp_entity_id" / "idp_certificate" / "idp_sso_url" / "idp_entity_id")
</command_excerpts>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Author docs/edition-deactivation.md (full operator runbook + data-fate matrix + destructive-path callout)</name>
  <files>docs/edition-deactivation.md</files>
  <read_first>
    - docs/saml.md (style anchor — read top-to-bottom; mirror tone, heading depth, callout shape, table shape; per D-07 this is the canonical style reference for new top-level operator docs)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-CONTEXT.md (D-01, D-02, D-07 are binding)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-RESEARCH.md (Pitfalls 1, 4 — destructive-path enumeration order; Pattern 1 — operator sequence)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-PATTERNS.md (operator-doc tone shared pattern; verification-by-grep discipline list)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-VALIDATION.md (LIFECYCLE-01 + LIFECYCLE-05 grep block — every literal string listed must appear verbatim)
    - backend/scripts/api-entrypoint.sh (lines 46-58 — conditional install the runbook quotes)
    - docker-compose.enterprise.yml (overlay activation contract referenced in step 3)
    - ~/Code/geolens-enterprise/geolens_enterprise/migrations/versions/e002_add_saml_columns.py (downgrade body — runbook quotes the deletion order accurately; do NOT paraphrase the order)
  </read_first>
  <action>
Create docs/edition-deactivation.md with the following exact section structure. Implements D-01 (overlay-removal canonical), D-02 (destructive alembic path documented with mandatory pg_dump), D-07 (top-level docs/, no subdir). Use ATX headings (`#`, `##`, `###`). Use ```bash``` blocks for shell commands and ```sql``` blocks for SQL snippets. Use `>` blockquote callouts with bold lead for warnings, mirroring saml.md:65-70.

REQUIRED LITERAL STRINGS (VALIDATION.md greps for every one — they MUST appear verbatim somewhere in the body):
- "pre-flight" (case-insensitive — at least once)
- "pg_dump" (verbatim)
- "oauth_providers" (verbatim — at minimum in the data-fate matrix and the pg_dump command)
- "docker compose down" (verbatim, lowercase)
- "GEOLENS_EDITION" (verbatim, all caps)
- "defense-in-depth" or "defense in depth" (either spelling acceptable; use "defense-in-depth" for consistency with CONTEXT.md)
- "destructive" (case-insensitive — at least once in the alembic-path section)
- "data-fate" or "data fate" (either spelling acceptable; recommend "data-fate" hyphenated as a section subhead)
- "edition-reactivation.md" (verbatim — cross-link target)
- "saml.md" (verbatim — IdP-side cleanup pointer)
- "mandatory" or "required" (either acceptable in the destructive-path callout)

SECTION-BY-SECTION SPEC:

1. **Title + audience callout (mirror saml.md:1-3):**
   ```markdown
   # Edition Deactivation: Enterprise → Community

   > **This runbook is for operators of an enterprise GeoLens deployment who need to downgrade to community edition** (license expiry, contract end, environment teardown, or moving SAML elsewhere). Community deployments do not have the enterprise overlay installed and do not need this procedure.
   ```

2. **At-a-glance table (mirror saml.md:7-13):**
   ```markdown
   | | Value |
   |---|---|
   | Canonical lever | Stop loading the `geolens-enterprise` overlay |
   | Defense-in-depth | Set `GEOLENS_EDITION=community` |
   | Schema fate (safe path) | 4 SAML columns and SAML rows survive — ready for reactivation |
   | Schema fate (destructive path) | `alembic downgrade -1` — see [Destructive Path](#destructive-path-permanent-decommissioning) |
   | Reactivation | See [`docs/edition-reactivation.md`](edition-reactivation.md) |
   ```

3. **`## Why overlay-removal is the canonical lever`** — 2-3 paragraphs explaining the architectural mechanism per D-01: `init_edition()` honors `GEOLENS_EDITION=community`, but typed accessors (`get_audit_extension()`, `get_branding_extension()`) do NOT consult `is_enterprise()` — they return whatever `register_extensions()` populated. So the env var alone leaves audit-export and branding overlays silently active. Overlay-removal at the entry-point discovery layer is the only complete deactivation. Quote backend/scripts/api-entrypoint.sh:46-58 inline as evidence:
   ```bash
   if [ -d "${ENTERPRISE_PATH}" ] && [ -f "${ENTERPRISE_PATH}/pyproject.toml" ]; then
       uv add --editable "${ENTERPRISE_PATH}"
   fi
   ```
   End with: "No `GEOLENS_ENTERPRISE_PATH` → no install → no entry point → no extension. Deactivation is structurally the inverse of activation."

4. **`## Data-fate matrix`** — markdown table near the top of the doc (per CONTEXT.md Claude's Discretion). Columns: data class × scenario. Use this exact shape (extend with rationale cells if helpful):
   ```markdown
   | Data class | Safe path (overlay removed) | Destructive path (`alembic downgrade -1`) |
   |---|---|---|
   | `catalog.oauth_providers` SAML rows | preserved | DELETED |
   | `catalog.oauth_providers` 4 deferred SAML columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`) | preserved (deferred=True keeps them off default queries) | DROPPED |
   | `catalog.oauth_accounts` SAML linkage rows | preserved | DELETED |
   | `catalog.users` rows with `auth_provider='oauth'` | preserved | preserved (e002.downgrade does not touch users) |
   | Audit log entries for SAML provider mutations | preserved | preserved (audit table is not in e002 scope) |
   | `chk_oauth_providers_type` CHECK constraint | relaxed (still allows `'saml'`) | re-tightened to `('oidc','google','microsoft')` |
   ```

5. **`## Pre-flight checklist`** — numbered list mirroring saml.md procedural style. Five concrete steps with ```bash``` and ```sql``` snippets:
   1. Snapshot SAML state with `pg_dump` (use this exact command — operators copy/paste):
      ```bash
      pg_dump -h <host> -U <user> -d <db> \
        --table catalog.oauth_providers \
        --table catalog.oauth_accounts \
        --table catalog.users \
        --data-only --column-inserts \
        > saml-state-pre-deactivation-$(date +%Y%m%d).sql
      ```
   2. Inventory live SAML usage:
      ```sql
      SELECT slug, display_name, enabled, created_at
      FROM catalog.oauth_providers
      WHERE provider_type = 'saml';
      ```
      Plus: count of users with `auth_provider='oauth'` linked via `oauth_accounts` to a SAML provider.
   3. Communicate to SAML-authenticated users. Insert this TODO marker (per CONTEXT.md "Risk surfaces" — Phase 221 ships LIFECYCLE-06):
      > **Existing SAML users will lose their login path.** Phase 221 ships the user re-onboarding procedure (`docs/edition-deactivation.md` → "Handling existing SAML users" section, planned). Until that lands, communicate the downgrade to SAML users out-of-band and convert their accounts manually via the admin UI (set local password or convert to OIDC).
   4. Plan a maintenance window. SAML logins fail immediately when the overlay is removed. Existing JWTs continue to work until they expire (per `ACCESS_TOKEN_EXPIRE_MINUTES`).
   5. Confirm the snapshot is restorable in a sandbox before proceeding.

6. **`## Deactivation sequence (canonical path)`** — six-step sequence per D-01. Each step gets a `### Step N: <title>` subhead with a ```bash``` block:
   - **Step 1: Stop the enterprise stack.** `docker compose down` (full container teardown — NOT `docker compose restart`, per RESEARCH.md "Risk surfaces" — stale entrypoint state in restart-without-rebuild can leave the previous container's writable layer holding the entry-point).
   - **Step 2: Restart without the enterprise overlay file.**
     ```bash
     # Community baseline — no -f docker-compose.enterprise.yml
     docker compose up -d --build
     ```
     Or for non-Docker deployments: `pip uninstall geolens-enterprise` (or remove the editable install: `uv remove geolens-enterprise`).
   - **Step 3: Optional defense-in-depth — set the edition env var.**
     ```bash
     # In your deployment env (e.g., .env or k8s ConfigMap)
     GEOLENS_EDITION=community
     ```
     > **`GEOLENS_EDITION=community` alone is incomplete deactivation.** Setting only the env var leaves the audit-export and branding overlays silently active in the registry. This step is defense-in-depth on top of overlay-removal — it makes `is_enterprise()` always return `False` even if a stale overlay accidentally loads. It does NOT replace step 1.
   - **Step 4: Verify SAML routes are gone.**
     ```bash
     curl -fsS http://localhost:8000/openapi.json | jq '.paths | keys[] | select(test("/auth/saml/"))' || echo "no SAML routes (expected)"
     # Should print nothing (empty result) or "no SAML routes (expected)".
     ```
   - **Step 5: Verify admin UI no longer shows the SAML SSO tab.** Sign in to the admin UI; the **SAML SSO** sidebar entry should be absent.
   - **Step 6: Verify backend logs show community mode.** Look for `edition=community` and an empty `features` list in the API startup logs (structured-log fields from `init_edition`).

   Note worker-process symmetry per RESEARCH.md Open Question 3: end the section with a single-line callout: "The worker container also receives the overlay; `docker compose down` removes both the API and worker containers symmetrically. No additional worker step required."

7. **`## Database state after the safe path`** — short paragraph reaffirming the matrix. Quote the deferred-column behavior: "The 4 SAML columns are physically present on `catalog.oauth_providers` (added by `e002_add_saml_columns`). The ORM marks them `deferred=True, deferred_group="saml"` — they are off default queries and only loaded via `select(...).options(undefer_group("saml"))`. Community deployments without the overlay never trigger that load, so the columns are inert."

8. **`## Destructive path: permanent decommissioning`** — clearly demarcated section with a strong opening callout. Per D-02 + RESEARCH.md Pitfall 4 — enumerate ALL data deleted, not just the columns:
   ```markdown
   > **The `alembic downgrade -1` path is destructive and irreversible without the pg_dump snapshot.** Use only when you need a clean schema (permanent license revocation AND your audit team requires no SAML data residue). For temporary deactivation, the safe path above is sufficient — the schema does no harm and reactivation is a clean re-mount.
   ```
   Then enumerate, in the exact order `e002.downgrade()` runs (per RESEARCH.md Pitfall 4):
   1. `DELETE FROM catalog.oauth_accounts WHERE provider_id IN (SELECT id FROM catalog.oauth_providers WHERE provider_type='saml')` — every SAML user's linkage row is dropped.
   2. `DELETE FROM catalog.oauth_providers WHERE provider_type='saml'` — every SAML provider row is dropped.
   3. The relaxed `chk_oauth_providers_type` CHECK is dropped.
   4. The strict `chk_oauth_providers_type` CHECK is recreated as `provider_type IN ('oidc','google','microsoft')`.
   5. The 4 SAML columns are dropped from `oauth_providers`.

   Mandatory pre-step (use this exact heading and verbatim text — VALIDATION.md greps for it):
   ```markdown
   ### Mandatory pre-step: pg_dump snapshot

   This step is **mandatory and required**. Without it, the deletion is unrecoverable.

   ```bash
   pg_dump -h <host> -U <user> -d <db> \
     --table catalog.oauth_providers \
     --table catalog.oauth_accounts \
     --table catalog.users \
     --data-only --column-inserts \
     > saml-state-pre-destructive-$(date +%Y%m%d).sql
   ```

   Confirm the dump is restorable in a sandbox before proceeding.
   ```

   Then the alembic command:
   ```bash
   uv run alembic downgrade -1
   ```

9. **`## Audit log limitation`** — single short paragraph (per CONTEXT.md Risk Surfaces): "Edition deactivation is not currently audit-logged at the platform level — operator-side change tickets are the audit trail. A future enhancement will emit a `lifecycle.deactivated` audit entry on `init_edition()` transitions."

10. **`## References`** — backtick-wrap path in link text + em-dash narrative (mirror saml.md:217-223):
    ```markdown
    - [`docs/edition-reactivation.md`](edition-reactivation.md) — community→enterprise re-upgrade procedure and post-reactivation verification.
    - [`docs/saml.md`](saml.md) — SAML setup, IdP configuration, and SAML-side cleanup pointers (disable the SAML app at the IdP after GeoLens-side deactivation).
    ```

DO NOT add an emoji anywhere in the doc (per project CLAUDE.md). DO NOT cite "AI" or "Bot" in any commit body when this work is later committed.
  </action>
  <verify>
    <automated>
test -f docs/edition-deactivation.md && \
grep -q -i 'pre-flight' docs/edition-deactivation.md && \
grep -q 'pg_dump' docs/edition-deactivation.md && \
grep -q 'oauth_providers' docs/edition-deactivation.md && \
grep -q -i 'docker compose down' docs/edition-deactivation.md && \
grep -q 'GEOLENS_EDITION' docs/edition-deactivation.md && \
grep -q -E 'defense.in.depth|defense-in-depth' docs/edition-deactivation.md && \
grep -q -i 'destructive' docs/edition-deactivation.md && \
grep -q -E -i 'mandatory|required' docs/edition-deactivation.md && \
grep -q 'edition-reactivation' docs/edition-deactivation.md && \
grep -q -E 'data.fate|data fate' docs/edition-deactivation.md && \
grep -q '(saml.md)' docs/edition-deactivation.md
    </automated>
  </verify>
  <acceptance_criteria>
    - File `docs/edition-deactivation.md` exists.
    - File contains literal token `pre-flight` (case-insensitive).
    - File contains literal token `pg_dump` (case-sensitive — it is a CLI tool name).
    - File contains literal token `oauth_providers` (case-sensitive — DB identifier).
    - File contains the literal phrase `docker compose down` (lowercase).
    - File contains literal token `GEOLENS_EDITION` (all-caps).
    - File contains either `defense-in-depth` or `defense in depth` (case-insensitive).
    - File contains the literal token `destructive` (case-insensitive) at least once.
    - File contains either `mandatory` or `required` (case-insensitive) in the destructive-path section.
    - File contains the literal text `edition-reactivation` somewhere (cross-link target).
    - File contains the literal text `(saml.md)` (markdown cross-link to saml.md).
    - File contains the literal token `data-fate` or `data fate` (case-insensitive).
    - File enumerates the destructive-path deletion order in the exact sequence `e002.downgrade()` runs (oauth_accounts DELETE → oauth_providers DELETE → CHECK rewrite → column drops).
    - File does NOT contain emojis (per CLAUDE.md).
    - File does NOT introduce a non-destructive alembic path (no `e003`-style suggestion — D-02 prohibits adding one).
  </acceptance_criteria>
  <done>docs/edition-deactivation.md is a complete operator runbook satisfying LIFECYCLE-01 (deactivation walkthrough end-to-end including pre-flight, sequence, env var labeled defense-in-depth) and LIFECYCLE-05 (destructive alembic path documented with mandatory pg_dump pre-step). All 12 grep assertions in &lt;automated&gt; pass.</done>
</task>

</tasks>

<verification>
- `bash -c '<automated grep block above>'` exits 0.
- File renders cleanly in GitHub markdown preview (no broken backtick blocks; no malformed tables).
- All 12 verification-by-grep tokens from PATTERNS.md "Verification-by-grep Discipline" appear in the body.
</verification>

<success_criteria>
- LIFECYCLE-01 satisfied: operator can read docs/edition-deactivation.md and execute the safe enterprise→community downgrade end-to-end (pre-flight, sequence, env var, verify, DB state confirmation).
- LIFECYCLE-05 satisfied: destructive alembic path is documented with mandatory pg_dump pre-step (per D-02; no non-destructive alembic added).
- D-01 honored: overlay-removal labeled canonical; GEOLENS_EDITION=community labeled defense-in-depth.
- D-02 honored: alembic downgrade documented as destructive with mandatory pg_dump; no e003 added.
- D-07 honored: top-level docs/ placement, no docs/lifecycle/ subdir.
</success_criteria>

<output>
After completion, create `.planning/phases/220-lifecycle-runbooks-and-preservation/220-01-SUMMARY.md` capturing: file path, section count, total line count, list of literal-string assertions verified, any deviations from this plan with rationale.
</output>
