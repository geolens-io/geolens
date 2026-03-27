---
phase: 260327-ism
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/quick/260327-ism-review-all-database-models-for-completen/260327-ism-REPORT.md
autonomous: true
requirements: [DB-REVIEW]

must_haves:
  truths:
    - "Report covers all 31 models across 11 modules"
    - "Every finding has a severity rating (critical/high/medium/low)"
    - "Each finding cites exact file paths and line numbers"
    - "Recommendations are actionable with specific SQL or model changes"
    - "No code or migration changes are made — documentation only"
  artifacts:
    - path: ".planning/quick/260327-ism-review-all-database-models-for-completen/260327-ism-REPORT.md"
      provides: "Comprehensive database model review report"
      min_lines: 200
  key_links: []
---

<objective>
Produce a comprehensive database model review report covering all 31 SQLAlchemy models in the GeoLens catalog schema. The report evaluates completeness, correctness, data integrity, indexing, and optimization opportunities.

Purpose: Give the developer a prioritized, actionable reference of every schema gap, drift issue, missing constraint, and optimization opportunity — without making any code changes.
Output: A single structured markdown report at `.planning/quick/260327-ism-review-all-database-models-for-completen/260327-ism-REPORT.md`
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260327-ism-review-all-database-models-for-completen/260327-ism-CONTEXT.md
@.planning/quick/260327-ism-review-all-database-models-for-completen/260327-ism-RESEARCH.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Verify research findings against current source</name>
  <files>
    backend/app/auth/models.py
    backend/app/auth/oauth/models.py
    backend/app/datasets/models.py
    backend/app/collections/models.py
    backend/app/maps/models.py
    backend/app/raster/models.py
    backend/app/jobs/models.py
    backend/app/audit/models.py
    backend/app/embed_tokens/models.py
    backend/app/embeddings/models.py
    backend/app/settings/models.py
    backend/app/search/saved.py
  </files>
  <action>
    Read every model file listed above. For each of the 25 findings in RESEARCH.md (H1-H7, M1-M12, L1-L6), confirm the finding still holds against the current source code. Specifically:

    1. Verify missing indexes (H1-H5): Confirm no `index=True` on the cited columns and no standalone index in `__table_args__`.
    2. Verify model/migration drift (H6-H7, L4): Confirm `__table_args__` still lacks the cited UniqueConstraint.
    3. Verify missing CHECK constraints (M1-M6, M8-M9): Confirm no CheckConstraint in `__table_args__` for the cited columns.
    4. Verify data integrity gaps (M7): Confirm VrtSourceLink has no unique constraint on `(vrt_dataset_id, source_dataset_id)`.
    5. Verify schema design observations (M10-M12, L5-L6): Confirm the cited patterns still exist.
    6. Verify lazy loading inconsistencies (L3): Scan all relationship() calls and catalog which lazy strategy each uses.

    Also scan for any NEW issues the research may have missed:
    - Any FK columns without indexes not already listed
    - Any String columns with known value sets but no CHECK
    - Any additional model/migration drift

    Record confirmation status and any new findings. Do NOT modify any files.
  </action>
  <verify>All 12 model files read. Each of the 25 findings confirmed or updated. Any new findings documented.</verify>
  <done>Complete verification ledger: every research finding tagged as confirmed/updated/invalidated, plus any net-new findings discovered.</done>
</task>

<task type="auto">
  <name>Task 2: Write the comprehensive review report</name>
  <files>.planning/quick/260327-ism-review-all-database-models-for-completen/260327-ism-REPORT.md</files>
  <action>
    Create the report at the path above. Use the verified findings from Task 1 and the RESEARCH.md as source material. Structure the report as follows:

    ## Report Structure

    ### Header
    - Title: "GeoLens Database Model Review"
    - Date, scope (31 models, 11 modules), methodology summary

    ### Executive Summary
    - 2-3 paragraph overview: schema is fundamentally sound, key concern areas, recommended priority actions
    - Summary statistics table (findings by severity)

    ### Model Inventory
    - Table of all 31 models: module, model name, table name, PK type, key relationships
    - Copied from RESEARCH.md inventory, verified against source

    ### Findings by Severity

    For each severity level (Critical, High, Medium, Low), list findings with:
    - **ID** (e.g., H1, M3)
    - **Title** (concise description)
    - **Affected model/table** and exact file path with line number
    - **Description** of the issue
    - **Impact** (what can go wrong, when it matters)
    - **Recommendation** with specific SQL or model code showing the fix
    - **Effort** estimate (trivial / small / medium)

    ### Positive Observations
    - Document the 10 strong patterns from RESEARCH.md that should be preserved
    - This section validates what is working well

    ### Prioritized Action Plan
    - Group recommendations into tiers:
      - Tier 1 (do first): Missing FK indexes (H1-H5) — immediate query performance benefit, zero risk
      - Tier 2 (do soon): Model/migration drift (H6-H7, L4) — prevents autogenerate surprises
      - Tier 3 (do when touching): CHECK constraints (M1-M9) — data integrity hardening
      - Tier 4 (consider): Schema design items (M10-M12, L5-L6) — longer-term improvements

    ### Appendix: Relationship Loading Strategy Audit
    - Table of all relationship() calls with their lazy strategy
    - Flag inconsistencies per L3

    Formatting rules:
    - Use severity badges: **CRITICAL**, **HIGH**, **MEDIUM**, **LOW**
    - Include exact file paths relative to repo root
    - SQL snippets in fenced code blocks with `sql` language tag
    - Python model fixes in fenced code blocks with `python` language tag
    - No emojis
  </action>
  <verify>
    <automated>test -f ".planning/quick/260327-ism-review-all-database-models-for-completen/260327-ism-REPORT.md" && wc -l ".planning/quick/260327-ism-review-all-database-models-for-completen/260327-ism-REPORT.md" | awk '{if ($1 >= 200) print "PASS: " $1 " lines"; else print "FAIL: only " $1 " lines"}'</automated>
  </verify>
  <done>Report exists at the target path with 200+ lines covering all 31 models, every confirmed finding with severity/impact/recommendation, positive observations, and a prioritized action plan.</done>
</task>

</tasks>

<verification>
- Report file exists at `.planning/quick/260327-ism-review-all-database-models-for-completen/260327-ism-REPORT.md`
- All 25+ findings from research are represented (confirmed or updated)
- Each finding has severity, file path, impact, and recommendation
- No source code files were modified
- Report includes model inventory, findings, positives, and action plan
</verification>

<success_criteria>
- Comprehensive markdown report covering all 31 models across 11 modules
- Every finding rated by severity with actionable recommendations
- Prioritized action plan grouping fixes by effort and impact
- Zero code changes — documentation only output
</success_criteria>

<output>
After completion, create `.planning/quick/260327-ism-review-all-database-models-for-completen/260327-ism-SUMMARY.md`
</output>
