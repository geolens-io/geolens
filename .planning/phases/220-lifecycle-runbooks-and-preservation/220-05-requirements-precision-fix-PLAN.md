---
phase: 220-lifecycle-runbooks-and-preservation
plan: 05
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/REQUIREMENTS.md
  - .planning/ROADMAP.md
autonomous: true
requirements:
  - LIFECYCLE-04

must_haves:
  truths:
    - "REQUIREMENTS.md LIFECYCLE-04 wording precisely says the 4 deferred columns are on `oauth_providers` (not `User`) — matches the actual schema (per RESEARCH.md Pitfall 5)"
    - "ROADMAP.md Phase 220 SC#4 wording mirrors the REQUIREMENTS.md fix"
    - "Edit is silent text-precision fix per CONTEXT.md Claude's Discretion (recommend silent fix as part of Phase 220's docs work)"
    - "All other content of REQUIREMENTS.md and ROADMAP.md unchanged (single-word/single-phrase fix on each file)"
  artifacts:
    - path: ".planning/REQUIREMENTS.md"
      provides: "Corrected LIFECYCLE-04 wording referencing oauth_providers (not User)"
      contains: "the 4 `deferred=True` SAML columns on `oauth_providers`"
    - path: ".planning/ROADMAP.md"
      provides: "Corrected Phase 220 SC#4 wording referencing oauth_providers (not User)"
      contains: "4 `deferred=True` `oauth_providers` columns"
---

<objective>
Fix the text-precision issue flagged in CONTEXT.md Claude's Discretion + RESEARCH.md Pitfall 5: REQUIREMENTS.md LIFECYCLE-04 and ROADMAP.md Phase 220 SC#4 currently say "the 4 `deferred=True` User columns" — the columns are on `catalog.oauth_providers`, NOT on `users`. Phase 220's other artifacts (test, runbooks) use the precise location; the requirement text should match.

Purpose: Removes the impedance mismatch between the requirement text and the actual schema. Prevents downstream confusion (a future engineer reading LIFECYCLE-04 and looking for SAML columns on `users` finds nothing — RESEARCH.md Pitfall 5 specifically warns about this scenario).

Output: Two single-line edits — one in REQUIREMENTS.md, one in ROADMAP.md.
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
@.planning/REQUIREMENTS.md
@.planning/ROADMAP.md
@backend/app/modules/auth/oauth/models.py

<schema_truth>
Per RESEARCH.md Pitfall 5 + backend/app/modules/auth/oauth/models.py:67-78:
- All 4 SAML columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`) are on `catalog.oauth_providers` with `deferred=True, deferred_group="saml"`.
- `users` table has NO SAML-specific columns.
- SAML users get `auth_provider='oauth'` (Phase 217 D-04) and link to providers via `oauth_accounts`.
</schema_truth>

<exact_targets>
**Target 1 — `.planning/REQUIREMENTS.md` line 24** (current verbatim):
```markdown
- [ ] **LIFECYCLE-04**: Disabling the enterprise edition (without running `alembic downgrade`) preserves `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` SAML columns on `User` — verified by an integration test that exercises the deactivate path.
```

**Target 1 replacement** (one-word fix `User` → `oauth_providers`):
```markdown
- [ ] **LIFECYCLE-04**: Disabling the enterprise edition (without running `alembic downgrade`) preserves `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` SAML columns on `oauth_providers` — verified by an integration test that exercises the deactivate path.
```

**Target 2 — `.planning/ROADMAP.md` line 80** (current verbatim):
```markdown
  4. An integration test runs in CI (`pytest -m lifecycle`) that exercises the deactivate path and asserts `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` User columns are intact after edition flag is toggled off
```

**Target 2 replacement** (two-word fix `User columns` → `` `oauth_providers` columns``):
```markdown
  4. An integration test runs in CI (`pytest -m lifecycle`) that exercises the deactivate path and asserts `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` `oauth_providers` columns are intact after edition flag is toggled off
```
</exact_targets>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix LIFECYCLE-04 wording in REQUIREMENTS.md and ROADMAP.md (two single-line edits)</name>
  <files>.planning/REQUIREMENTS.md, .planning/ROADMAP.md</files>
  <read_first>
    - .planning/REQUIREMENTS.md (current state of LIFECYCLE-04 line — typically line 24)
    - .planning/ROADMAP.md (current state of Phase 220 SC#4 — typically line 80)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-PATTERNS.md (lines 467-498 — exact replacement text spelled out)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-CONTEXT.md (Claude's Discretion section — recommendation: silent fix as part of Phase 220's docs work)
    - backend/app/modules/auth/oauth/models.py (lines 67-78 — schema-truth source: 4 SAML columns are on `oauth_providers`)
  </read_first>
  <action>
Make exactly TWO single-line edits, no other modifications to either file.

**Edit 1 — `.planning/REQUIREMENTS.md` LIFECYCLE-04**:

Find the line that starts with `- [ ] **LIFECYCLE-04**: Disabling the enterprise edition` (currently around line 24). Replace the substring `the 4 \`deferred=True\` SAML columns on \`User\`` with `the 4 \`deferred=True\` SAML columns on \`oauth_providers\``.

The minimal diff is:
```diff
-the 4 `deferred=True` SAML columns on `User`
+the 4 `deferred=True` SAML columns on `oauth_providers`
```

Final line state (verify after edit):
```markdown
- [ ] **LIFECYCLE-04**: Disabling the enterprise edition (without running `alembic downgrade`) preserves `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` SAML columns on `oauth_providers` — verified by an integration test that exercises the deactivate path.
```

**Edit 2 — `.planning/ROADMAP.md` Phase 220 SC#4**:

Find the line that starts with `  4. An integration test runs in CI` under `### Phase 220:` (currently around line 80). Replace the substring `4 \`deferred=True\` User columns` with `4 \`deferred=True\` \`oauth_providers\` columns`.

The minimal diff is:
```diff
-4 `deferred=True` User columns
+4 `deferred=True` `oauth_providers` columns
```

Final line state (verify after edit):
```markdown
  4. An integration test runs in CI (`pytest -m lifecycle`) that exercises the deactivate path and asserts `oauth_providers` rows with `provider_type='saml'` and the 4 `deferred=True` `oauth_providers` columns are intact after edition flag is toggled off
```

**Constraints:**
- Each file's edit MUST be a one-line modification only. Total `git diff --numstat` for each file should show 1 line removed + 1 line added (or 2 lines added/removed if your editor splits the change).
- DO NOT modify any other line in REQUIREMENTS.md or ROADMAP.md.
- DO NOT modify the LIFECYCLE-04 traceability table entry (line ~64 in REQUIREMENTS.md) — that line says "LIFECYCLE-04 | Phase 220 | Pending" and is correct as-is.
- DO NOT update line 80 of REQUIREMENTS.md ("Last updated: 2026-04-29 — traceability filled in by roadmapper..." or similar metadata footer) — leave the footer alone; the wording fix is a content fix, not a metadata refresh.
- Preserve trailing whitespace, line endings, and surrounding blank lines exactly as they are pre-edit. Use `git diff` to confirm scope before considering the task done.
  </action>
  <verify>
    <automated>
# After-edit positive checks: corrected wording present
grep -q 'the 4 `deferred=True` SAML columns on `oauth_providers`' .planning/REQUIREMENTS.md && \
grep -q '4 `deferred=True` `oauth_providers` columns' .planning/ROADMAP.md && \
# After-edit negative checks: legacy wording GONE
! grep -q 'SAML columns on `User`' .planning/REQUIREMENTS.md && \
! grep -q '4 `deferred=True` User columns' .planning/ROADMAP.md && \
# Diff scope: each file changed at most ~5 lines (single-line edit + possible whitespace nudge)
[ "$(git diff --numstat .planning/REQUIREMENTS.md | awk '{print $1+$2}')" -le 5 ] && \
[ "$(git diff --numstat .planning/ROADMAP.md | awk '{print $1+$2}')" -le 5 ]
    </automated>
  </verify>
  <acceptance_criteria>
    - `.planning/REQUIREMENTS.md` contains the literal string `the 4 \`deferred=True\` SAML columns on \`oauth_providers\``.
    - `.planning/REQUIREMENTS.md` does NOT contain the legacy literal string `SAML columns on \`User\``.
    - `.planning/ROADMAP.md` contains the literal string `4 \`deferred=True\` \`oauth_providers\` columns`.
    - `.planning/ROADMAP.md` does NOT contain the legacy literal string `4 \`deferred=True\` User columns`.
    - `git diff --numstat .planning/REQUIREMENTS.md` shows ≤ 5 total added+removed lines.
    - `git diff --numstat .planning/ROADMAP.md` shows ≤ 5 total added+removed lines.
    - Both files' line counts (wc -l) match pre-edit counts (the edit replaces in place, doesn't add lines).
  </acceptance_criteria>
  <done>REQUIREMENTS.md LIFECYCLE-04 and ROADMAP.md Phase 220 SC#4 both reference `oauth_providers` precisely. The schema truth (Pitfall 5) and the requirement text are aligned. No other lines modified.</done>
</task>

</tasks>

<verification>
- Two grep-positive assertions pass.
- Two grep-negative assertions pass.
- Diff scope ≤ 5 lines per file confirms targeted single-line edit (not a rewrite).
</verification>

<success_criteria>
- Text-precision issue closed (CONTEXT.md Claude's Discretion + RESEARCH.md Pitfall 5).
- Phase 220's other artifacts (test asserting on `oauth_providers`, runbook describing `oauth_providers`) are now consistent with the requirement text.
- No scope creep — only the single-word/phrase fix on each file.
</success_criteria>

<output>
After completion, create `.planning/phases/220-lifecycle-runbooks-and-preservation/220-05-SUMMARY.md` capturing: line numbers edited, before/after of each replacement, total diff size per file.
</output>
