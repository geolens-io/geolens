---
phase: 220-lifecycle-runbooks-and-preservation
plan: 03
type: execute
wave: 1
depends_on: []
files_modified:
  - docs/saml.md
autonomous: true
requirements:
  - LIFECYCLE-03

must_haves:
  truths:
    - "docs/saml.md no longer presents `alembic downgrade -1` as the primary deactivation path (LIFECYCLE-03 + ROADMAP SC#3)"
    - "docs/saml.md Installation section cross-links to docs/edition-deactivation.md (per D-03)"
    - "docs/saml.md labels the alembic path as destructive/opt-in with a mandatory data-export prerequisite"
    - "All other sections of saml.md (IdP configs, hardening defaults, troubleshooting, audit, security posture) stay byte-identical (per D-03 + Anti-Pattern 5: targeted edit only)"
  artifacts:
    - path: "docs/saml.md"
      provides: "Retargeted Installation section + new 'Deactivating SAML' subsection (LIFECYCLE-03)"
      contains:
        - "edition-deactivation.md"
        - "destructive"
        - "Deactivating SAML"
  key_links:
    - from: "docs/saml.md"
      to: "docs/edition-deactivation.md"
      via: "markdown link in retargeted bullet + new subsection"
      pattern: "edition-deactivation"
---

<objective>
Surgically edit docs/saml.md Installation section to retarget the existing "reversible (`alembic downgrade -1`)" framing and add a short "Deactivating SAML" subsection that points operators at docs/edition-deactivation.md as the primary deactivation path. Implements D-03 + LIFECYCLE-03.

Purpose: ROADMAP SC#3 requires saml.md no longer present `alembic downgrade -1` as the primary deactivation path. This is a TARGETED edit — exactly two changes — not a rewrite. All other sections (IdP configs, hardening defaults, troubleshooting, audit, security posture) stay byte-identical.

Output: Modified docs/saml.md (one bullet replaced + one subsection added; rest unchanged).
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

<exact_target>
**Existing line to replace** — docs/saml.md line 48 (verbatim, current state):
```
The migration is reversible (`alembic downgrade -1` removes the columns and re-tightens the CHECK), but downgrading destroys any SAML provider rows. Back up first.
```

**Surrounding context** (saml.md:43-58, do NOT modify any line outside the target):
- Line 43-47 is the migration-effects numbered list (`1. Adds four nullable columns...` / `2. Relaxes the chk_oauth_providers_type CHECK...`).
- Line 48 is the line to replace.
- Line 50-55 is the "Verify the overlay loaded" block.
- Line 57 is the "If the SAML routes are missing..." paragraph.

The new "Deactivating SAML" subsection lands AFTER line 57 (after the existing verify block + missing-routes paragraph), as the last subsection within `## Installation` before the `## IdP Configuration` heading at saml.md:59.
</exact_target>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Surgically edit docs/saml.md Installation section (replace one line + add one subsection)</name>
  <files>docs/saml.md</files>
  <read_first>
    - docs/saml.md (current state — read top to bottom to confirm line 48 is still the target line and lines 1-31 / 59+ remain identical to PATTERNS.md's analysis; preserve byte-identity outside the targeted scope)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-CONTEXT.md (D-03 binding; D-07 confirms top-level cross-link target)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-RESEARCH.md (Pattern 2 — exact replacement text; Anti-Pattern 5 — do NOT rewrite saml.md beyond the targeted edit)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-PATTERNS.md (the file's analog map — replacement text spelled out verbatim in lines 314-339)
    - .planning/phases/220-lifecycle-runbooks-and-preservation/220-VALIDATION.md (LIFECYCLE-03 grep block — negative + positive checks)
  </read_first>
  <action>
Make exactly TWO changes to docs/saml.md. No other modifications.

**Change 1 — Replace line 48 (the "reversible" bullet) in place** with this blockquote (per D-03 + RESEARCH.md Pattern 2):

```markdown
> **To deactivate SAML, see [`docs/edition-deactivation.md`](edition-deactivation.md).**
> The canonical path leaves the schema alone — your SAML provider rows and the
> 4 deferred SAML columns persist through deactivation, ready for reactivation.
>
> The `alembic downgrade -1` path is destructive: it deletes
> `oauth_accounts` SAML rows, deletes `oauth_providers` SAML rows, and drops
> the 4 SAML columns. Use only for permanent decommissioning. Mandatory pre-step:
> `pg_dump --table catalog.oauth_providers --table catalog.oauth_accounts --table catalog.users`.
> Without this dump, the deletion is unrecoverable.
```

The replacement preserves the surrounding context: the migration-effects numbered list (lines 43-47) immediately above stays unchanged; the "Verify the overlay loaded" block immediately below (originally line 50+) stays unchanged.

**Change 2 — Add a new `### Deactivating SAML` subsection** immediately after the "If the SAML routes are missing..." paragraph (originally saml.md:57) and immediately before the `## IdP Configuration` heading (originally saml.md:59). Use this exact text:

```markdown
### Deactivating SAML

To turn SAML off, follow the canonical path in [`docs/edition-deactivation.md`](edition-deactivation.md). The TL;DR: stop loading the `geolens-enterprise` overlay (drop `docker-compose.enterprise.yml` from your compose stack or `pip uninstall geolens-enterprise`) and restart. Your SAML provider rows survive; your users' identities survive; reactivation is a clean re-mount.
```

The `###` heading nests under `## Installation`, matching the existing heading depth structure.

**Do NOT modify any other line in saml.md.** Per Anti-Pattern 5 (RESEARCH.md): only the existing "reversible" bullet + this short subsection. IdP configurations, hardening defaults, troubleshooting, audit, security posture, limitations all stay byte-identical.

**Verification of the edit:**
1. The negative grep `grep -E 'migration is reversible.*alembic downgrade' docs/saml.md` MUST return no matches (the legacy line at saml.md:48 is gone).
2. The positive grep `grep -q 'edition-deactivation.md' docs/saml.md` MUST return at least 2 matches (one in the replaced bullet, one in the new subsection).
3. The positive grep `grep -q -i 'destructive' docs/saml.md` MUST match (the alembic-path label).
4. The positive grep `grep -q 'Deactivating SAML' docs/saml.md` MUST match (the new subsection heading).
5. Lines 1-42 (Title, Overview, "Installation" heading + opening paragraph + first bash block + numbered migration-effects list) MUST be byte-identical to the pre-edit state.
6. Lines starting from the unchanged `## IdP Configuration` MUST be byte-identical to the pre-edit state.

If your editor's whitespace handling adds or removes trailing whitespace anywhere outside the targeted edit region, restore the original whitespace exactly. Use `git diff docs/saml.md` to confirm the diff is limited to (a) the replaced bullet around line 48 and (b) the inserted subsection just above `## IdP Configuration`.
  </action>
  <verify>
    <automated>
# Negative: legacy framing GONE
! grep -E 'migration is reversible.*alembic downgrade' docs/saml.md && \
# Positive: cross-link present (at least once; expect 2+ in practice)
grep -q 'edition-deactivation.md' docs/saml.md && \
# Positive: destructive label present
grep -q -i 'destructive' docs/saml.md && \
# Positive: new subsection heading present
grep -q 'Deactivating SAML' docs/saml.md && \
# Diff scope: at most ~25 lines added/removed (one bullet replaced + one subsection added);
# guards against accidental whole-file rewrite
[ "$(git diff --numstat docs/saml.md | awk '{print $1+$2}')" -lt 35 ]
    </automated>
  </verify>
  <acceptance_criteria>
    - `grep -E 'migration is reversible.*alembic downgrade' docs/saml.md` returns no matches (negative check — legacy line gone).
    - `grep -c 'edition-deactivation.md' docs/saml.md` returns 2 or more (cross-link in replaced bullet AND in the new "Deactivating SAML" subsection).
    - `grep -q -i 'destructive' docs/saml.md` matches (the alembic path is labeled destructive).
    - `grep -q 'Deactivating SAML' docs/saml.md` matches (new subsection heading).
    - `grep -q 'pg_dump' docs/saml.md` matches (mandatory pre-step in the replaced bullet).
    - `git diff --numstat docs/saml.md` shows fewer than 35 total added+deleted lines (proves the edit is targeted, not a rewrite).
    - `git diff docs/saml.md` shows zero changes to lines 1-42 (Title through migration-effects list).
    - `git diff docs/saml.md` shows zero changes from `## IdP Configuration` heading onward (lines 59+).
    - File contains no emojis.
  </acceptance_criteria>
  <done>docs/saml.md Installation section retargeted: line 48's "reversible alembic" framing replaced with a destructive-labeled blockquote pointing at edition-deactivation.md; new "Deactivating SAML" subsection added at the end of the Installation section. All other sections of saml.md byte-identical. LIFECYCLE-03 satisfied.</done>
</task>

</tasks>

<verification>
- Negative grep for "migration is reversible.*alembic downgrade" returns no matches.
- Cross-link to edition-deactivation.md present at least twice.
- "destructive" label present.
- "Deactivating SAML" subsection heading present.
- Total diff ≤ 35 lines (changed/added).
- Visual inspection confirms IdP Configuration / Hardening / Troubleshooting / Audit / Security Posture sections are byte-identical to pre-edit.
</verification>

<success_criteria>
- LIFECYCLE-03 satisfied: docs/saml.md no longer presents `alembic downgrade -1` as the primary path; explicitly labels it destructive/opt-in; cross-links to docs/edition-deactivation.md as the primary deactivation procedure.
- D-03 honored: targeted edit, not a rewrite.
- ROADMAP SC#3 satisfied verbatim.
</success_criteria>

<output>
After completion, create `.planning/phases/220-lifecycle-runbooks-and-preservation/220-03-SUMMARY.md` capturing: line numbers of the two edit regions, total diff size, before/after of the negative grep, before/after of the positive greps.
</output>
