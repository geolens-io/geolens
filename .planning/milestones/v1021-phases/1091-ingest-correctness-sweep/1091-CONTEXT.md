# Phase 1091: Ingest Correctness Sweep - Context

**Gathered:** 2026-05-23
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

An operator running `docker compose down -v && up -d --build` and then `python3 scripts/seed-natural-earth.py --base-url http://localhost:8080 --username admin --password admin` sees zero `status=failed` rows in `/api/admin/jobs/` AND any failures that *do* appear in the future cannot escape the seed script's exit-print summary.

**Two requirements:**

- **INGEST-01** — Fix the `urban_areas_landscan_10m` quicklook generation failure surfacing as `MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here` in `app/processing/ingest/tasks_common.py` during the post-commit quicklook phase. Reproducible: 1 in 109 datasets from the Natural Earth seed reliably trips the failure. Data lands cleanly (`record_status=published`, `feature_count=6018`) but the ingest job row is `status=failed` and the dataset has no quicklook.

- **OPS-01** — Add post-loop reconciliation to `scripts/seed-natural-earth.py` so the script's "Succeeded: N, Failed: M" summary cannot disagree with the persisted worker job-row status. After the polling loop completes, `GET /api/admin/jobs/?status=failed` and report any failures in the Import Summary block.

**Sequencing rationale (from ROADMAP.md):** OPS-01's reconciliation regression test consumes INGEST-01's MissingGreenlet shape — natural intra-phase dependency. Spike-first per v1019/v1020 pattern: identify the exact async-context boundary line(s) BEFORE the fix lands.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting. Use ROADMAP phase goal, REQUIREMENTS.md acceptance criteria, and codebase conventions to guide decisions.

### Locked from REQUIREMENTS.md
- **Spike-first** — short investigation deliverable (`.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md` or inline in `1091-01-SUMMARY.md`) identifies the exact async-context boundary line(s) BEFORE the fix lands.
- **Regression test** — `backend/tests/test_quicklook_async_context.py` (or equivalent) reproduces the original `MissingGreenlet` shape under the pre-fix code path; node-ID pinned in REQUIREMENTS.md traceability table per TD-13 `req_citation_pinning` rule.
- **Reconciliation contract** — `scripts/seed-natural-earth.py` exits non-zero AND prints failed-job table when failures exist; preserves current exit-zero + green-summary when no failures.
- **Out of scope:** broader `tasks_common.py` refactor; only the MissingGreenlet bug is in scope.

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research. Known seed surfaces:
- `backend/app/processing/ingest/tasks_common.py` — quicklook commit-phase code (where `MissingGreenlet` originates)
- `backend/app/processing/ingest/tasks_vector.py` — vector ingest task; surfaces the error log line `Ingest task failed`
- `scripts/seed-natural-earth.py` — seed script with `--base-url` + `--username/--password` flags; reports `Succeeded: N, Failed: M` heuristic at the end
- `/api/admin/jobs/` endpoint (already in use during quick task 260523-at1) — supports `?status=failed&limit=N` query

</code_context>

<specifics>
## Specific Ideas

**Reproduction case** (live, reproducible at start of phase):
- Job `90254766-ca62-4db4-86c5-411d1c9061fe` on `ne_10m_urban_areas_landscan.zip` → `urban_areas_landscan_10m` (dataset UUID `ffcba726-d61c-48e9-8786-3b41b5fc96f8`)
- Error: `MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here. Was IO attempted in an unexpected place?`
- Phase: `commit`, table: `urban_areas_landscan_10m`, task: `ingest_file`
- Antecedent log line: `quicklook_failed` warning citing `Can't reconnect until invalid transaction is rolled back`

**Spike hypothesis** (from quick-task 260523-at1 SUMMARY): "Likely root cause: the quicklook commit-phase code path attempts a sync sqlalchemy call (or accesses a lazy-loaded relationship) from outside an async greenlet context. Probably `tasks_common.py` around the quicklook-write block on the commit phase. Repeatable enough that the seed reliably trips it on one specific dataset (urban_areas_landscan) but not the other 108 — feature shape may matter (multipolygon vs other geometry, or row count)."

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. New failure shapes that emerge under the same `MissingGreenlet` code path get caught by INGEST-01's regression test, but discovery of *different* failure shapes is a future milestone per REQUIREMENTS.md `Future Requirements`.

</deferred>
