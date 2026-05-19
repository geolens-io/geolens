# Phase 1053: Quickstart Docs + Environment Hardening - Context

**Gathered:** 2026-05-19
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss=true)

<domain>
## Phase Boundary

A new user following `docs.getgeolens.com/guides/quickstart/` can bring up GeoLens and seed initial data without discovering scripts independently or hitting undocumented blockers.

**8 requirements:** DOC-01, DOC-02, DOC-03, DOC-04, DOC-05, BU-03, EW-01, EW-04.

**Source-of-truth for every finding:** `.planning/M001-7n8vpc-dry-run-audit.md` (gitignored, 815 lines). Each REQ-ID maps 1:1 to a finding ID in that report — read the matching `## DOC-XX` / `## BU-XX` / `## EW-XX` section for full Where / Documented behavior / Actual behavior / Recommendation.

</domain>

<decisions>
## Implementation Decisions

### Cross-repo split (LOCKED — milestone-level decision)

**5 of 8 requirements ship via PRs in `~/Code/getgeolens.com/.planning/`, NOT this repo:**

- **DOC-01** — Quickstart documents the API-seeder path. Edit: `getgeolens.com/docs/guides/quickstart/`.
- **DOC-02** — `seed-ago-data.py` API-key documentation. Choice: docs-only fix in `getgeolens.com/docs/guides/quickstart/` (preferred, cheapest), OR a script enhancement in this repo (`scripts/seed-ago-data.py`) adding `--username/--password`. Planner decides which.
- **DOC-03** — Quickstart prereqs add Python 3.10+ + httpx. Edit: `getgeolens.com/docs/guides/quickstart/`.
- **DOC-04** — Quickstart "1-2 minutes" claim. Edit: `getgeolens.com/docs/guides/quickstart/`.
- **DOC-05** — Quickstart documents interactive credential prompt. Edit: `getgeolens.com/docs/guides/quickstart/`.

**3 of 8 requirements ship in this repo:**

- **BU-03** — Apple Silicon `linux/amd64` platform-mismatch warning. Touch: `docker-compose.yml` (`platform: linux/amd64` declarations) and/or quickstart docs. If docs-only choice, classify under cross-repo.
- **EW-01** — Single-compose path canonical. Touch: `docker-compose.yml` + possibly `docker-compose.demo.yml` consolidation (or relabel demo as optional). Probably touches `install.sh` + quickstart docs too.
- **EW-04** — `.env.example` SSL hint. Touch: `.env.example` (single-file edit; defense-in-depth against BU-01 regression that shipped `7b168bde`).

### Cross-repo execution mechanics

The planner should produce a `getgeolens.com` planning artifact list that the executor can hand off, NOT try to edit nonexistent files in this repo. Reasonable shapes:

- **Plan structure A (2 sibling repos in scope):** Each cross-repo doc edit is a plan step that says "Open `~/Code/getgeolens.com`, edit `docs/guides/quickstart/index.md` section X, commit there". Executor uses `cd ~/Code/getgeolens.com && ...`.
- **Plan structure B (this-repo handoff doc):** A new file in `~/Code/getgeolens.com/.planning/cross-repo-handoff/v1012-quickstart-fixes.md` lists every doc change to make over there. Then a single getgeolens.com PR closes them all. Slight overhead but cleaner.

Recommended: **Plan structure A** — direct cross-repo edits with full commits there, since the doc changes are scoped to the quickstart page only.

### EW-03 status — already shipped (do not redo)

The audit's EW-03 (`install.sh` wait-for-health) shipped at `b4ad03d9` on 2026-05-19 as one of the 3 Critical fixes folded into the v1.2.0 release. Credit-only — no work for this phase.

### DOC-04 decision space

The "1-2 minutes" claim can be (a) replaced with a measured range, (b) removed entirely in favor of the `install.sh` wait-for-health output (now reliable per `b4ad03d9`), or (c) tightened to "typically under 2 minutes; install.sh will report when ready". Planner picks. Simplest: (b) defer to `install.sh` output.

### BU-03 decision space

Apple Silicon warning sources: most likely the postgres + redis images (no native arm64 builds — or there are but compose isn't selecting them). Two paths:
- **(a) Suppress** — add `platform: linux/amd64` to affected services in docker-compose.yml so compose stops emitting the warning. Tradeoff: forces emulation even on amd64 hosts (slight perf cost; usually harmless).
- **(b) Document as expected** — keep the warning, add a quickstart note "Apple Silicon users will see `WARNING: The requested image's platform (linux/amd64) does not match the detected host platform... this is expected and harmless`."

Recommended: **(b) document** — keeps amd64 hosts unaffected and is honest about emulation. Cheaper.

### EW-01 decision space

`docker-compose.demo.yml` exists alongside `docker-compose.yml` and is referenced in the audit's DOC-01 as "the separate demo compose the project wants gone". Two paths:
- **(a) Consolidate** — merge demo seeders/services into main compose under a `--profile demo` gate. Quickstart loses the "demo compose" detour entirely.
- **(b) Relabel** — keep demo compose as-is but rewrite the quickstart so the single-compose path is canonical and the demo compose is "an optional convenience for the bundled demo".

Recommended: **(b) relabel + DOC-01 quickstart rewrite** — lower-risk, defers compose surgery; consolidation can be a future stand-alone phase if/when worth the test churn.

</decisions>

<code_context>
## Existing Code Insights

**Files most likely to touch (this repo):**

- `docker-compose.yml` — BU-03 platform note (if chosen path (a))
- `.env.example` — EW-04 SSL hint (definitive — one-line addition with comment)
- `scripts/seed-ago-data.py` — DOC-02 IF planner chooses script-enhancement path (add `--username/--password` mirroring `seed-natural-earth.py`'s self-mint pattern)

**Files most likely to touch (`~/Code/getgeolens.com`):**

- `docs/guides/quickstart/*` (whatever the actual file structure is — planner should look first) — DOC-01..05, BU-03 docs path, EW-01 relabel

**Reference patterns:**

- `scripts/seed-natural-earth.py:272,317` — was the SEED-01 bootstrap fix (`/api/auth/login/` → `/api/auth/login`); shows the `--username/--password` self-mint pattern that DOC-02 might lift if going script-enhancement route.
- `b4ad03d9` (EW-03 already shipped) — `install.sh` wait-for-health gate. Shows the kind of UX the quickstart can now lean on.

</code_context>

<specifics>
## Specific Ideas

Each requirement is concretely sourced in the audit. Per requirement:

- **DOC-01** → audit `## DOC-01` + audit `## EW-01` + audit `## EW-02` (all three describe the same fix from different angles)
- **DOC-02** → audit `## DOC-02`
- **DOC-03** → audit `## DOC-03`
- **DOC-04** → audit `## DOC-04`
- **DOC-05** → audit `## DOC-05`
- **BU-03** → audit `## BU-03`
- **EW-01** → audit `## EW-01`
- **EW-04** → audit `## EW-04`

The audit's "Recommendation" line in each section is the implementation directive.

</specifics>

<deferred>
## Deferred Ideas

- **`docker-compose.yml` + `docker-compose.demo.yml` consolidation** — explicitly deferred per EW-01 decision space (b). Captured as a future phase if worth the test-churn investment.
- **Full `seed-ago-data.py` rewrite to use the GeoLens SDK** — out of scope per REQUIREMENTS.md "Out of Scope" table. DOC-02 only requires usability documentation OR a minimal `--username/--password` patch.

</deferred>
