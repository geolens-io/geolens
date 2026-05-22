# Phase 1086: Process Tightening + Close Gate - Context

**Gathered:** 2026-05-22
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Two process artifacts are committed, TD-07 runtime symmetry is confirmed in the deployed images, and v1019 ships with a full close-gate audit trail and both tags cut.

This is the milestone close. Three goals:
1. **TD-13 process tightening**: prevent the two drift patterns surfaced in v1018 (REQ-paraphrased test names vs actual node-IDs, and executor SUMMARY checkbox-flip miss) via repo retro + global skill file updates
2. **TD-14 runtime symmetry**: rebuild api/worker containers so TD-07 (`connect_args["ssl"]=False` on disable branch from v1018 Phase 1080-02) is live in deployed images, then probe to confirm
3. **Close gate**: CHANGELOG `[1.5.4]`, full close-gate (sequential pytest + e2e:smoke:builder + Playwright MCP 5/5 surfaces), local tag `v1019` + public tag `v1.5.4`

</domain>

<decisions>
## Implementation Decisions

### Pre-locked decisions from REQUIREMENTS.md / user direction:
- **TD-13 lands in TWO places** (both): repo retro + global skill update
  - Repo retro: `.planning/retros/v1019-process.md` — project-scoped narrative of the two v1018 incidents that drove the rule changes
  - Global skill update: `~/.claude/get-shit-done/` — touch `agents/gsd-planner` (REQ authoring nodeID rule), `agents/gsd-executor` (SUMMARY checkbox flip before commit), `templates/requirements.md` (nodeID schema example)
- **TD-14 runtime probe**: `docker compose up -d --build api worker`, then `docker exec <api> grep -n "ssl=False" app/core/config.py` confirms the v1018 Phase 1080-02 line is in the running image
- **Close-gate** uses Playwright MCP for the live 5/5 smoke surfaces per user direction (`--use-playwright-mcp` flag to autonomous run)
- **Tag pair**: local `v1019` + public `v1.5.4`

### Plan structure:
- Plan 1086-01: TD-13 process tightening (repo retro + 3 global skill file updates)
- Plan 1086-02: TD-14 runtime symmetry + close gate (docker rebuild + ssl=False probe + CHANGELOG + full close-gate + tag cutting)

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research. Expected touch points:
- `.planning/retros/v1019-process.md` — new file (the repo retro)
- `~/.claude/get-shit-done/agents/gsd-planner.md` (or similar) — global GSD planner agent skill
- `~/.claude/get-shit-done/agents/gsd-executor.md` — global executor skill
- `~/.claude/get-shit-done/templates/requirements.md` — global REQUIREMENTS template
- `docker-compose.yml` — api + worker service definitions
- `backend/app/core/config.py:database_connect_args` — TD-07 source from v1018 Phase 1080-02
- `CHANGELOG.md` — `[1.5.4]` entry

</code_context>

<specifics>
## Specific Ideas

**Plan 1086-01 specifics (TD-13):**
- Repo retro narrative should cover:
  - v1018 TD-02/03 paraphrased-test-name incident (`test_register_password_too_short` / `test_register_password_diversity` cited in REQ but actual targets `test_register_emits_user_register_audit` / `test_register_disabled_does_not_emit_audit`)
  - v1018 `tasks_common.py` path drift (cited `backend/app/platform/jobs/` but actual `backend/app/processing/ingest/`) and line drift (231/237 vs 232/238)
  - v1018 Plan 1081-02 executor closed TD-05 in code but didn't flip REQUIREMENTS.md checkbox (commit `5bf63166` fixed inline mid-audit)
- Skill updates should be additive — add explicit rules, don't rewrite existing skill files
  - gsd-planner: "REQ-cited test names must be `path::TestClass::test_name` validated against `git grep` before commit. Production-code citations must include path + line, also validated against `git grep`."
  - gsd-executor: "Before SUMMARY commit, executor MUST flip the REQUIREMENTS.md checkbox `[ ]` → `[x]` and traceability row Pending → Complete for every requirement closed in this plan."
  - requirements.md template: add a "good requirement" example using a `path::TestClass::test_name` node-ID

**Plan 1086-02 specifics (TD-14 + close gate):**
- TD-14:
  - `docker compose up -d --build api worker` (rebuilds both images so v1018 Phase 1080-02's ssl=False change is included)
  - `docker exec geolens-api-1 grep -n "ssl=False" app/core/config.py` — must show the line from v1018 Phase 1080-02 (target: a line like `connect_args["ssl"] = False` or equivalent on the disable branch)
- Close gate:
  - CHANGELOG.md `[1.5.4] - 2026-05-22` entry covering TD-09..TD-14 + WR-01 fix
  - Sequential `uv run pytest backend/` — must pass at 3032+/0/38 (Phase 1085 baseline) or close
  - `npm run e2e:smoke:builder` — must exit green (matches v1017/v1018 baseline 25-26/1)
  - Live Playwright MCP smoke 5 surfaces (e.g., `/`, `/maps`, `/datasets/<id>`, `/maps/<id>` editor, `/maps/<id>` viewer) — 5/5 PASS with 0 console errors
  - Cut local tag `v1019` + public tag `v1.5.4` at the post-baseline commit
  - Update STATE.md `status` to `shipped` + milestone close metadata

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. All TD-13 + TD-14 + close-gate scope is fixed by REQUIREMENTS.md.

</deferred>
