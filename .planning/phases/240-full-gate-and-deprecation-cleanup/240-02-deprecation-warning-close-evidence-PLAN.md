---
phase: 240-full-gate-and-deprecation-cleanup
plan: "02"
type: execute
wave: 2
depends_on:
  - 240-01
files_modified:
  - docs-internal/audits/post-impl-20260504-v13-6.md
  - .planning/v13.6-MILESTONE-AUDIT.md
  - .planning/phases/240-full-gate-and-deprecation-cleanup/240-VERIFICATION.md
  - .planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md
  - .planning/ROADMAP.md
  - .planning/REQUIREMENTS.md
  - .planning/STATE.md
autonomous: true
requirements:
  - DEBT-02
must_haves:
  truths:
    - The Pydantic, Alembic, and Authlib deprecation warnings observed in focused backend verification are inventoried with source, count, and current owner.
    - Local warnings are fixed where a minimal project-side change is safe; upstream or broad migration warnings are documented with owner/versioned follow-up.
    - Focused maps/search backend verification is rerun after any warning-related code change and remains green.
    - v13.6 close evidence is updated to clearly state whether TD-01 and TD-02 are closed or still accepted residual risk.
  artifacts:
    - path: .planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md
      provides: Deprecation-warning inventory, fixes/deferrals, and DEBT-02 evidence
    - path: .planning/phases/240-full-gate-and-deprecation-cleanup/240-VERIFICATION.md
      provides: Phase 240 verification record for DEBT-01 and DEBT-02
    - path: .planning/v13.6-MILESTONE-AUDIT.md
      provides: Refreshed milestone audit status after cleanup evidence
  key_links:
    - from: .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md
      to: .planning/phases/240-full-gate-and-deprecation-cleanup/240-VERIFICATION.md
      via: DEBT-01 broader-gate evidence feeds final phase verification
      pattern: "DEBT-01"
    - from: docs-internal/audits/post-impl-20260504-v13-6.md
      to: .planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md
      via: Warning debt from Phase 239 close evidence
      pattern: "Pydantic|Alembic|Authlib|deprecation"
    - from: .planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md
      to: .planning/v13.6-MILESTONE-AUDIT.md
      via: Final TD-02 disposition and milestone audit refresh
      pattern: "TD-02|DEBT-02"
---

<objective>
Close DEBT-02 and refresh v13.6 close evidence after Phase 240 cleanup.

Purpose: inventory the existing deprecation warnings from focused backend verification, fix what is safely project-owned, document any upstream or broad migration warnings, and update the milestone audit/phase verification so v13.6 can be re-audited cleanly.

Output: warning-cleanup summary, Phase 240 verification, refreshed milestone audit, and planning-state updates.
</objective>

<execution_context>
@/Users/ishiland/.codex/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.codex/get-shit-done/templates/summary.md
@.agents/skills/geolens-test-audit/SKILL.md
@.agents/skills/geolens-post-impl/SKILL.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/STATE.md
@.planning/v13.6-MILESTONE-AUDIT.md
@.planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md
@docs-internal/audits/post-impl-20260504-v13-6.md

Phase 239 focused pytest passed with 16 warnings from existing Pydantic, Alembic, and Authlib deprecations. This plan closes TD-02 / DEBT-02 by either removing project-owned warnings or documenting exact follow-up for warnings that should not be fixed inside v13.6.

Known worktree constraint: unrelated user changes may exist. Do not revert or commit unrelated files.
</context>

<tasks>
<task type="auto">
  <name>Inventory warning sources</name>
  <files>.planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md</files>
  <action>Run the focused backend command in warning-visible mode. Capture warning categories, source files, counts, and whether each warning is project-owned, dependency-owned, or migration-sized.</action>
  <verify>
    <automated>cd backend &amp;&amp; env PYTHONPATH=. POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_maps.py tests/test_search.py tests/test_hybrid_search.py tests/test_search_facets.py tests/test_search_cache.py tests/test_vrt_catalog_175.py -q -W default</automated>
  </verify>
  <done>The warning inventory names Pydantic, Alembic, and Authlib warning sources with ownership and count.</done>
</task>

<task type="auto">
  <name>Fix safe project-owned warnings</name>
  <files>backend, .planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md</files>
  <action>For warnings that can be fixed with small, low-risk local changes, patch the owning files, run targeted tests around the changed surface, and rerun the focused maps/search command. Do not perform broad dependency upgrades or large framework migrations in this phase; document those as owner/versioned follow-up instead.</action>
  <verify>
    <automated>cd backend &amp;&amp; env PYTHONPATH=. POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_maps.py tests/test_search.py tests/test_hybrid_search.py tests/test_search_facets.py tests/test_search_cache.py tests/test_vrt_catalog_175.py -q</automated>
  </verify>
  <done>All safe project-owned warning fixes are applied and the focused maps/search command remains green.</done>
</task>

<task type="auto">
  <name>Document deferred warning follow-up</name>
  <files>.planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md, docs-internal/audits/post-impl-20260504-v13-6.md</files>
  <action>For remaining warnings, record exact source, reason it remains, owner area such as backend platform, migrations, or auth dependency, a versioned/backlog follow-up target, and why it does not block v13.6 closure.</action>
  <verify>
    <automated>rg -n "Pydantic|Alembic|Authlib|deprecation|follow-up|owner" .planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md docs-internal/audits/post-impl-20260504-v13-6.md</automated>
  </verify>
  <done>Remaining warnings have explicit non-blocking disposition and follow-up ownership.</done>
</task>

<task type="auto">
  <name>Refresh close evidence</name>
  <files>docs-internal/audits/post-impl-20260504-v13-6.md, .planning/v13.6-MILESTONE-AUDIT.md, .planning/phases/240-full-gate-and-deprecation-cleanup/240-VERIFICATION.md, .planning/ROADMAP.md, .planning/REQUIREMENTS.md, .planning/STATE.md</files>
  <action>Update the close audit with DEBT-02 warning disposition, refresh `.planning/v13.6-MILESTONE-AUDIT.md` with TD-01/TD-02 status, create Phase 240 verification, and mark Phase 240 completion in ROADMAP/REQUIREMENTS/STATE only if DEBT-01 and DEBT-02 are verified.</action>
  <verify>
    <automated>test -s .planning/phases/240-full-gate-and-deprecation-cleanup/240-VERIFICATION.md</automated>
    <automated>rg -n "DEBT-01|DEBT-02|TD-01|TD-02" .planning/phases/240-full-gate-and-deprecation-cleanup/240-VERIFICATION.md .planning/v13.6-MILESTONE-AUDIT.md docs-internal/audits/post-impl-20260504-v13-6.md</automated>
  </verify>
  <done>Close evidence and planning state accurately reflect Phase 240 results.</done>
</task>

<task type="auto">
  <name>Write warning cleanup summary</name>
  <files>.planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md</files>
  <action>Write `240-02-SUMMARY.md` with warning inventory, fixes applied and rerun evidence, deferred follow-up if any, and final DEBT-02 disposition.</action>
  <verify>
    <automated>test -s .planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md</automated>
    <automated>rg -n "DEBT-02|Pydantic|Alembic|Authlib|deprecation" .planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md</automated>
  </verify>
  <done>`240-02-SUMMARY.md` contains enough command and warning evidence to close or explicitly defer DEBT-02.</done>
</task>
</tasks>

<verification>

Required before summary completion:
- Focused maps/search pytest command rerun after warning cleanup or documentation.
- `test -s .planning/phases/240-full-gate-and-deprecation-cleanup/240-VERIFICATION.md`
- `test -s .planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md`
- `rg -n "DEBT-01|DEBT-02|TD-01|TD-02|Pydantic|Alembic|Authlib|deprecation" .planning/phases/240-full-gate-and-deprecation-cleanup/240-VERIFICATION.md .planning/phases/240-full-gate-and-deprecation-cleanup/240-02-SUMMARY.md .planning/v13.6-MILESTONE-AUDIT.md docs-internal/audits/post-impl-20260504-v13-6.md`

</verification>
