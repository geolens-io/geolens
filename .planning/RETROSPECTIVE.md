# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1018 — Hygiene — v1017 Tech-Debt Tail

**Shipped:** 2026-05-21
**Phases:** 4 (1080-1083) | **Plans:** 8 | **Requirements:** 8/8 | **Tags:** `v1018` (local) + `v1.5.3` (public) at `d1b76061`

### What Was Built

- **TD-01 (Phase 1080):** Two `# broad:` justification comments on `except Exception:` clauses at `tasks_common.py:232,238` inside `_job_phase_session` (comment-only edit; rollback invariant preserved).
- **TD-07 (Phase 1080):** Explicit `connect_args["ssl"] = False` on the `database_ssl_mode == "disable"` branch of `database_connect_args`; `if/elif` chain restructured; 3-branch shape pinned with 4-test `TestDatabaseConnectArgs` + 5-test `TestExternalPooler`.
- **WR-01 (Phase 1080 inline review fix):** Third broad-except at `tasks_common.py:1030` justified + `test_layering.py:1577` regex fixed from `\s+` to `[ \t]+` (portable ERE) — closed a latent CI failure mode caused by macOS `git grep -E` not expanding `\s` as whitespace.
- **WR-02 (Phase 1080 inline review fix):** `test_verify_full_returns_ssl_context_with_verify` restructured — was a dead test that constructed a `verify-full` Settings object then asserted on a `require`-mode object instead.
- **TD-02/TD-03 (Phase 1081):** Two register-audit test password fixtures updated from `"securepass123"` to `"TestPass1234!"` (13-char, 4/4 SEC-S16 classes).
- **TD-05 (Phase 1081):** `patch("app.modules.catalog.sources.security.validate_url_for_ssrf", new=AsyncMock())` added to both `TestServiceReuploadWorker` tests at the defining-module path (correct for lazy body-level from-import in `tasks_reupload.py:347`).
- **TD-06 (Phase 1081):** Added `client` fixture arg to `test_job_phase_session_none_branch_rolls_back_on_exception` — transitively triggers `conftest.py`'s `db_module.async_session = test_session_factory` monkey-patch, fixing full-suite cross-loop pool contamination.
- **TD-04 (Phase 1082):** `AsyncMock(side_effect=IngestionError(...))` patch on `router_reupload.run_service_preview` at the caller-namespace path (correct for module-top from-import) — removes `ogrinfo` CLI host dependency while preserving IDOR/auth invariant.
- **TD-08 (Phase 1083):** PYTEST-BASELINE-v1018.md (3025/0/38 sequential, 0 InvalidCatalogNameError); frontend gates (tsc 0, vitest 2105/2105, e2e:smoke:builder 25/1); CHANGELOG [1.5.3]; tags `v1018` + `v1.5.3` at `d1b76061`; live MCP smoke 5/5 surfaces green.

### What Worked

- **Audit-first roadmap definition.** The v1017 audit's `frontmatter.deferred_to_v1018` was a clean machine-readable list of 8 items — REQUIREMENTS.md TD-01..TD-08 mapped one-to-one. Zero scope ambiguity going into Phase 1080.
- **Planner caught upstream doc drift in real time.** Phase 1080 planner caught that `tasks_common.py` had moved from `platform/jobs/` to `processing/ingest/` and the broad-except lines were 232/238 not 231/237. Phase 1081 planner caught that TD-02/TD-03 REQUIREMENTS.md test names (`test_register_password_too_short`, `test_register_password_diversity`) didn't exist in code — the real names are `test_register_emits_user_register_audit` / `test_register_disabled_does_not_emit_audit`. Saved 2-3 executor cycles each.
- **Code review caught a latent CI failure.** WR-01 was a third broad-except invisible to the layering test on macOS because Apple Git's `-E` doesn't expand `\s` as whitespace. Linux CI would have caught it; macOS dev never would have. Fixed dual-half (source + test regex portability) in one commit.
- **Executor Rule 1 deviation (Phase 1082) on patch-target nuance.** The planner specified the defining-module path for `run_service_preview`, but `router_reupload.py:44` uses a module-top `from` import (vs `tasks_reupload.py:347`'s lazy body-level from-import). Module-top binding requires patching the caller namespace; defining-module patch is a silent no-op. Executor caught this on first test run and fixed it inline.
- **Live MCP smoke as orchestrator-driven pre-tag gate.** Caught the v1008 `/maps/new` 422 console-noise pattern (PASS-with-note, not a regression — reproduced on v1017) and confirmed 0 console errors on all 5 surfaces of the rebuilt stack. Headless e2e and unit tests both missed the empty-state route quirk.

### What Was Inefficient

- **TD-05 traceability row was stale at audit time.** Plan 1081-02's SUMMARY commit closed the requirement but didn't flip the REQUIREMENTS.md checkbox. Integration check caught it mid-audit — required a small mid-audit fix commit. Future: bake "update REQUIREMENTS.md checkbox + traceability row" into the executor's standard SUMMARY workflow, not just the plan's `<output>` block.
- **REQUIREMENTS.md drift went undetected until planning time.** The TD-02/TD-03 test-name paraphrase ("password_too_short" / "password_diversity" instead of the actual "emits_user_register_audit" / "disabled_does_not_emit_audit") slipped through both the audit narrative AND the milestone-init review. Pattern: requirement descriptions written in narrative form drift from the actual test artifact names. Mitigation candidate: requirements should reference exact pytest nodeIDs when pinning tests.

### Patterns Established

- **Same-line `# broad: <reason>` justification per layering test contract.** Codebase has 138 of 139 existing sites using `# broad:` (preferred). `# noqa: BLE001 <reason>` is the fallback when ruff would object to BLE001. The layering test does a simple substring match on the raw `git grep -E` output — no AST, no regex on the comment, no requirement for a multi-line preceding comment.
- **Caller-namespace vs defining-module patch target rule.** When patching a function imported via `from x import y`: (1) module-top imports bind the symbol at module load → patch the CALLER namespace; (2) lazy body-level imports rebind per call → patch the DEFINING module. Surfaced via Plan 1082 executor Rule 1 deviation. Future Python mock targets should explicitly cite which case applies.
- **macOS BSD vs GNU `grep -E` regex portability.** `\s+` in BRE/ERE is GNU-only — Apple Git uses BSD libc which treats `\s` as literal `s`. Always use `[ \t]+` for whitespace matching in portable layering rules. Same trap exists for `\d`, `\w`, etc.
- **client-fixture transitive monkey-patch resolves cross-loop binding.** `test_tasks_common_phase_brackets.py` had 4 tests that pulled `test_db_session` (which depends on `client`, which monkey-patches `db_module.async_session = test_session_factory`) — only the failing test was a bare bracket caller. Adding `client` as a fixture arg fixed the cross-loop contamination without touching the production code that Plan 1080 had just justified.
- **AsyncMock with side_effect=DomainException preserves existing handler-mapping semantics.** TD-04 mock raises `IngestionError` to drive the existing `except IngestionError → HTTPException(502)` branch, preserving the test's existing `status_code in (400, 502)` assertion. Returning a canned success dict would have pushed past the exception handler into the success path and broken the test.

### Key Lessons

1. **Hygiene milestones still produce meaningful pattern surfaces.** 8 named TD items + 2 inline review fixes + 3 cross-cutting patterns (broad-except justification shape, patch-target rule, regex portability) = high learning density per LOC changed.
2. **Audit-driven scoping zero-defects-to-execute when the audit is rigorous.** v1017's audit was machine-readable in frontmatter; v1018 roadmap had zero ambiguity about scope. Future milestone audits should always emit the deferred-items list in YAML frontmatter for the next milestone's REQUIREMENTS.md to consume directly.
3. **Live MCP smoke is the canonical pre-tag gate for any milestone touching the backend.** v1018 was backend-only (test + 1 production-code branch) but live MCP caught the `/maps/new` console-noise pattern that was invisible to headless e2e. Worth the 10-minute orchestrator-driven cost even on hygiene milestones.
4. **REQUIREMENTS.md should reference exact test nodeIDs, not paraphrased descriptions.** v1018's TD-02/TD-03 drift cost a planner cycle to detect and document. Future test-pinning requirements should use the literal `path::TestClass::test_name` form.

### Cost Observations

- Model mix: ~30% opus (planning), ~70% sonnet (execution + review + verification)
- Sessions: 1 (start-to-archive in single autonomous run via `/gsd-autonomous --from 1080`)
- Notable: Zero v1018.1 carry-forward — all 2 code-review warnings fixed inline, 0 deferrals to v1019. Hygiene milestones can close cleanly when the deferred-items list is well-scoped and tested.

---

## Milestone: v1011.1 — Builder Hygiene Carryover

**Shipped:** 2026-05-18
**Phases:** 1 (1052) | **Plans:** 7 | **Requirements:** 5/5 | **Tag:** `v1011.1` (local at `567c701e`)

### What Was Built

Closed all 4 EMRG-FN findings carried forward from v1011 Phase 1051 Plan 12 (EMRG-01 triage) in a single hygiene phase:

- **EMRG-FN-01 Path A REMOVE**: BasemapSublayerEditorScene STROKE section + zoom inputs + 5 dead-stub callbacks deleted; live opacity slider + Reset section preserved (planner narrowed CONTEXT.md's over-broad scope). 5 orphan basemapSublayer i18n keys × 4 locales removed. Test 14 regression pin added (5 positive-form `queryBy*` assertions). Inline disposition comment per INV-01 pattern.
- **EMRG-FN-02**: `settings.toggleWidget` orphan i18n key removed from all 4 locales.
- **EMRG-FN-03**: 2 unused `eslint-disable-next-line` directives removed from `UnifiedStackPanel.tsx` (planner-time grep caught line drift 679→735, 720→776).
- **EMRG-FN-04**: SublayerConfigIndicators `layer={null}` closure documented via Test 1 docstring extension (CONTEXT.md auto-resolution claim was wrong — Plan 06 caught + corrected; live callsite remains at `UnifiedStackPanel.tsx:556`).
- **CTRL-01**: typecheck 0 / vitest 1979/1979 / e2e:smoke:builder 26/26 / i18n 2/2; CHANGELOG `[Unreleased]` v1011.1 block; inline WR-01 fix (orphan vi.mock removed); local tag `v1011.1` at `567c701e`.
- **Live Playwright MCP re-verify**: orchestrator drove against `localhost:8080` — 6/6 surface checks pass, 0 console errors.

### What Worked

- **Hygiene-shape carryforward pattern at 5th iteration**: v1009.1 → v1010.1 → v1010.2 → v1011 → v1011.1. The pattern is now reflex — single phase, sequential plans, single CTRL-01 close gate. No new decisions needed at milestone-shaping time.
- **Planner-time grep gate caught 3 CONTEXT.md inaccuracies before execution**: (1) Plan 01 REMOVE scope was over-broad in CONTEXT.md (would have deleted live opacity + Reset); (2) EMRG-FN-04 auto-resolution claim was wrong (live callsite at `UnifiedStackPanel.tsx:556` remains post-Path A); (3) EMRG-FN-03 line numbers had drifted (REQUIREMENTS cited 679+720; actual 735+776). Each correction was encoded in the plan files so the executor never re-introduced the original mistake.
- **CTRL-01 Half A / Half B split**: deterministic gates (typecheck/vitest/e2e/i18n/CHANGELOG/tag) delegated to executor; orchestrator-only MCP re-verify ran inline after code-review. Clean division of labor.
- **Post-shipping code review caught 1 WARNING + 1 INFO**: WR-01 (orphan `vi.mock('../StyleColorPicker')` factory) had been explicitly deferred by Plan 03's executor as "orphaned but harmless." Per `feedback_review_findings_inline.md`, fixed inline (and moved the tag) — zero v1011.2 deferrals.
- **Live MCP re-verify as pre-tag gate**: vitest JSDOM-render confirmed component-level absence of removed surfaces, but live MCP confirmed the production page never paints the surfaces on real basemap sublayer click. Same axis of confidence as v1010.1 / v1010.2 / v1011 MCP runs.

### What Was Inefficient

- **CONTEXT.md drafted in early planning had 3 inaccuracies**. The planner-time grep gate caught all 3, but the orchestrator could have caught them at CONTEXT-authoring time by running a quick grep before locking the decision. Cost: ~5 min of planner work to encode corrections; cost-saving if caught earlier: 0 (planner catches it for free).
- **Plan 07 executor created the `v1011.1` tag prematurely** at `017af020` instead of waiting for orchestrator's "all clear" after Half B. Tag had to be moved to `567c701e` after WR-01 fix. Not catastrophic (tag operations are cheap), but breaks the implicit contract that the tag commit is the final HEAD. Next time: explicitly instruct executor to STAGE the tag (write a TAG-CANDIDATE.md note) instead of creating it.
- **191 stale historical quick-task artifacts surfaced at pre-close audit**. These are pre-existing repo noise (not v1011.1-introduced), but the `audit-open` output dwarfed the actual v1011.1 close items. A periodic `.planning/quick/` cleanup pass would shrink the audit signal-to-noise ratio.

### Patterns Established

- **Planner-time correction encoded in plan files** — when the planner catches a CONTEXT.md inaccuracy, the plan file documents the correction so the executor cannot re-introduce the original mistake. (3 examples from Plan 01 / 05 / 06.)
- **Sticky basemap LIVE behaviors during sublayer scope reduction** — when removing dead UI from a shared scene (e.g., BasemapSublayerEditorScene), the planner must verify which sections remain live before approving deletion. Opacity + Reset were the load-bearing survivors here.
- **`layer={null}` as a deliberate production case** — the SublayerConfigIndicators contract treats `layer={null}` as "render nothing" specifically for basemap sublayer rows in UnifiedStackPanel; this is intentional, not an oversight. Documented inline at Test 1.

### Key Lessons

- **Run grep before locking CONTEXT.md decisions.** Catching CONTEXT.md inaccuracies at authoring time is cheaper than planner-time correction encoding — and dramatically cheaper than executor-time deviation handling.
- **Live MCP re-verify is justified pre-tag overhead** for any UI REMOVE work. JSDOM tests prove the component-level absence; only MCP proves the production page never paints the removed surfaces on real interaction.
- **"Orphaned but harmless" deferrals invite WARNING-level code-review findings.** If a test mock survives a production removal, fix it inline at removal time — don't write a SUMMARY note saying "harmless." The next code reviewer (human or agent) will flag it and the tag will move.

### Cost Observations

- Model mix: opus (planner) + sonnet (executors × 7, verifier, code reviewer, code fixer) + sonnet (orchestrator)
- Sessions: 1 (this end-to-end /gsd-autonomous run)
- Notable: planner correction work added ~15 min vs locked-CONTEXT.md flow, but saved at least 1 executor deviation cycle per correction caught.

---

## Milestone: v1010.1 — Live Playwright MCP Smoke

**Shipped:** 2026-05-17
**Phases:** 1 (1049) | **Plans:** 1 | **Tasks:** 11 | **Requirements:** 7/7

### What Was Built

- Fresh-stack interactive Playwright MCP smoke check (login → builder load → 5 v1010 win-surface passes) executed end-to-end inside the Claude orchestrator context (no executor delegation — Playwright MCP is orchestrator-scoped).
- `SMOKE-FINDINGS.md` artifact with 8 classified findings (2 P0 / 2 P1 / 4 P2) and per-finding disposition.
- 3 inline P0/P1 fixes shipped + verified post-fix in the same MCP session:
  - SF-01: `BulkActionBar` confirm-click reaches `onBulkDelete` (outside-click guard extended via `data-bulk-action-bar` marker).
  - SF-02: render-mode swap dispatches non-circle modes through `handleRenderAsChange` + `buildRenderAsPatch()` (`LayerEditorPanel` cast removed, `RenderAsId` widened).
  - SF-03: `StyleJsonDialog` lazy mount gated on `showStyleJson` instead of just `id` truthy.
- 1 P1 deferred-with-rationale (SF-04 tile source dedup → tracked as `BUILDER-PERF-DEDUPE-SOURCES` tech-debt).

### What Worked

- **Live MCP smoke caught what headless e2e missed.** v1010 closed with green e2e:smoke gates, yet a 30-minute interactive MCP run found 2 P0 regressions in v1010's marquee win surfaces (bulk-delete + render-mode swap). The interactive smoke is now a justified pre-tag gate — not redundant with headless e2e.
- **Fetch instrumentation via `browser_evaluate` proved decisive for SF-01.** When `performance.getEntriesByType('resource')` showed the bulk-delete POST never fired, monkey-patching `window.fetch` from inside the MCP session gave conclusive evidence (no entries) that ruled out network-layer issues and pointed at React event dispatch. The document-level capture-phase click listener then identified the unmount-before-click race.
- **Backend regression-check via direct `fetch()` saved diagnostic time.** Confirming the backend bulk-delete endpoint worked end-to-end via in-browser `fetch()` (with the existing auth token from `localStorage`) before deep-diving the frontend chain meant ~5 minutes of bisect instead of an hour.
- **Hygiene-shape milestone (1 phase, 1 plan, ~30min execution) repeated cleanly.** v1009.1 → v1010.1 cadence confirms the pattern: one smoke pass per major builder milestone, find what slipped, fix-or-defer with disposition.

### What Was Inefficient

- **Initial SF-01 hypothesis (stale closure) was wrong.** Spent ~10min on the prop-closure trail before pivoting to instrumenting the document capture phase. The faster path would have been: instrument document capture FIRST, prove the click isn't reaching React handler, then look at what consumed the event. Add to playbook: "when a click handler appears not to fire, capture-phase document listener before closure analysis."
- **TaskUpdate hook spam.** Every other turn produced a reminder to update tasks even when work was actively in-flight. Future hygiene smoke runs should pre-create all tasks at start and avoid mid-task captures unless work truly stops.

### Patterns Established

- **The "data-{marker}" hatch for portaled/sticky widgets vs sentinel-ref guards.** First seen for the Radix DropdownMenu portal in SP-01 (Phase 1045), now extended to the sticky-footer BulkActionBar in SF-01. Any future "outside-click should be treated as inside" case should follow this pattern: add `data-{name}="true"` to the widget root, add a `.closest('[data-{name}="true"]')` check in the outside-click handler.
- **Unsafe enum cast as a smell.** `option.id as 'narrow-subset'` when `option.id` is the full union is a strong signal that the consumer's handler is missing branches for the rest of the union. Fixed in SF-02; worth a follow-up sweep across `handleRenderModeChange`-style narrow-cast call sites.
- **React.lazy() resolves on component mount, not on what the component returns.** Any `<Suspense><LazyDialog open={false}/></Suspense>` defeats the lazy contract. The right pattern is `{shouldShow && <Suspense><LazyDialog/></Suspense>}`. Update to PB-05 / lazy-load guidance.

### Key Lessons

- Interactive smoke after every major builder milestone catches user-blocking regressions that pass headless gates. Cheap (~30min) for the coverage delta — keep the pattern.
- When a UI affordance "does nothing," the diagnostic ladder is: (1) capture-phase document listener for the click → (2) instrument the actual handler entry → (3) prop closures last. The reverse takes 3× longer.
- Verify the backend endpoint independently of the UI before bisecting the frontend chain. Avoids chasing a frontend ghost when the API genuinely changed.
- For verification milestones, treat Playwright MCP as the orchestrator's primary test surface — don't delegate to a subagent that lacks MCP access.

### Cost Observations

- Single session, ~30min for full discover-fix-reverify cycle on 3 inline fixes.
- Model: Opus 4.7 1M (driving Playwright MCP directly from orchestrator context).
- Notable: All 3 fixes diagnosed + shipped + re-smoked without spawning a single subagent — the MCP-driven verification pattern keeps the loop tight.

## Milestone: v1010 — Builder Performance & Code Quality

**Shipped:** 2026-05-16
**Phases:** 3 (1046, 1047, 1048) | **Plans:** 12 | **Tasks:** ~37 | **Requirements:** 17/17

### What Was Built

- Audit-first milestone: Phase 1046 produced `BUILDER-CODE-AUDIT.md` (24 findings across 5 dimensions) + `BUILDER-PERF-BASELINE.md` (6 PERF axes + 8 bottlenecks PB-01..PB-08), giving Phase 1047 a concrete prioritized fix list.
- Phase 1047 shipped 6 wave-sequential plans closing all P0 + all PERF: lazy-load 6 editor scenes (-17.3% entry chunk); `coalesceFrame` rAF utility + 100ms/200ms debounces; `POST /api/maps/{id}/layers/bulk-delete` (50→1 HTTP, -98%); LayerStyleEditor 1231 → 468 LOC (-62%) via per-render-mode split + RenderModeSwitch lookup-table.
- Phase 1048 hygiene-shape closeout: popup_config visible-error surface + 3 UI-REVIEW polish carry-overs; Add Data modal audit (13 findings, 0 P0, v1008 ALIGNED); SourcesTab 8 `it.todo` items → 9 live tests; 7/7 smoke gates PASS including all 4 Phase 1047 deferred Docker gates; CHANGELOG `[Unreleased]` populated with measured numbers.

### What Worked

- **Audit-first sequencing** (Phase 1046 → Phase 1047 → Phase 1048) — kept fix scope concrete; Phase 1047 planners cited specific finding IDs without re-investigating; no rework cycles.
- **Wave-sequential single-plan execution** — 6 waves of 1 plan each in Phase 1047 produced clean atomic commits and clear before/after metric capture per wave. The wave model added minimal overhead since each wave was sequential anyway.
- **Bundled UI-REVIEW carry-overs into next phase's Plan 01** — 3 minor polish items from Phase 1047 UI audit (cursor scope, text-[13px], partial-failure suffix) absorbed into Phase 1048 Plan 01 alongside popup_config UX. Avoided a tiny standalone polish phase.
- **Closeout Plan 04 absorbed deferred Docker gates** — Phase 1047 verification status `human_needed` upgraded to `passed` after Phase 1048 CLOSE-01 ran all 4 Docker-dependent gates. Single human-verify checkpoint at milestone close instead of one per phase.
- **Plan-checker pre-execution catches** — the plan-checker for Phase 1047 explicitly noted Plan 04 → Plan 05 LayerStyleEditor.tsx file-overlap and the executor honored the dependency chain. No mid-execution conflicts.

### What Was Inefficient

- **Plan filename naming drift** — first planner emitted `1047-PLAN-NN-slug.md` per the orchestrator's explicit instruction, but the SDK's `init.execute-phase` plan discovery requires the `-PLAN.md` suffix. Required a rename commit before execution could see the plans. Root cause: my plan-phase prompt to the planner specified the wrong convention. Fix forward: orchestrator prompts must say `{padded_phase}-{plan_id}-{slug}-PLAN.md`, not `{padded_phase}-PLAN-{plan_id}-{slug}.md`. Memory entry warranted.
- **Code review auto-fix loop** found a real BLOCKER (CR-01 in Phase 1048: popup_config pre-check false-positive when `dataset_column_info` is null) that the verifier missed — verifier read the SUMMARY and saw "8 tests pass" rather than reasoning about edge-case input shape. Suggests: code-review post-execute is load-bearing; never skip it.
- **Executor occasional API 500** — Plan 02 spawn hit a transient API error after the agent did real work; retry produced different-but-valid implementation. Lost ~5 min; no data loss because the prior attempt left no commits. Mitigation: if executor errors mid-plan, always check `git log` before re-dispatching.

### Patterns Established

- **Hygiene-milestone close pattern reinforced** — Phase 1048 used 4 sequential plans (FOLLOWUP × 3 + CLOSE) with a single human-verify checkpoint at end. Matches `feedback_hygiene_milestone_pattern.md` memory. Worth keeping as the default for closeout phases.
- **Per-PERF before/after capture in plan SUMMARY** — each Phase 1047 plan dropped a measured delta directly in its own SUMMARY frontmatter or sidecar, making the Phase 1047 Plan 06 PERF-BEFORE-AFTER.md table a roll-up rather than re-measurement.
- **Same-day milestone (open → ship)** — v1010 opened and closed 2026-05-16. Three phases ran under autonomous mode with a single user gate (the Docker validation decision). Demonstrates `/gsd:autonomous` as a viable shape for tight scope milestones with clear audit inputs.

### Key Lessons

1. **The `*-PLAN.md` suffix is load-bearing** — the SDK's plan-discovery regex (`endsWith('-PLAN.md')`) is the single source of truth for what counts as a plan. Custom plan-naming schemes break execute-phase silently. Always end with `-PLAN.md`.
2. **VERIFICATION.md `human_needed` is upgrade-able post-hoc** — Phase 1047's status was upgraded from `human_needed` to `passed` after Phase 1048's CLOSE-01 closed the deferred Docker gates. Cleaner audit story than carrying `human_needed` into milestone close.
3. **Reviewer's structural depth beats verifier's surface check on edge-case bugs** — the code-review agent caught a null-pointer-like false-positive that VERIFICATION (which trusted SUMMARY counts) missed. Code review is not redundant with verification.
4. **Bundle wins are gated by hot-path constraints** — Phase 1047 Plan 02 hit -18% entry-chunk reduction (vs -40% forecast in Phase 1046 PB-01) because `LayerEditorPanel` is the hot path and cannot be lazy-loaded without first-paint regression. Bundle baselines should distinguish "could lazy-load" from "should lazy-load."

### Cost Observations

- Model mix: ~30% opus (planner Phase 1047 + Phase 1048; planner-heavy reasoning), ~70% sonnet (executor x10, reviewer x2, fixer x2, verifier x2, UI agents x3).
- Sessions: 1 long autonomous session via `/gsd:autonomous --from 1047` with one user gate (deferred Docker validation routing to 1048).
- Notable: 12 sequential plans across 2 phases in a single session pushed close to context-window pressure; the lifecycle steps (audit → archive → retrospective → tag) all completed in the same context without `/clear`. Could split tighter on a longer milestone.

## Milestone: v1003 — Builder v1 Hardening

**Shipped:** 2026-05-12  
**Phases:** 5 (1014-1018) | **Plans:** 5 | **Requirements:** 24/24

### What Was Built

- Browser-backed regression coverage for the redesigned Map Stack, Add Dataset modal, tablet sidebar clamp, and scoped accessibility flows.
- Duplicate-rendering coverage from both row overflow and Add Dataset modal entry points, with independent sibling-layer styling.
- RenderAs and schema-preservation tests proving v1 modes patch existing writable fields and never write `is_3d`.
- Basemap and terrain integration hardening proving controls write only existing map-level fields.
- Saved-map, public-viewer, and shared-viewer compatibility coverage for duplicate renderings, zoom range, basemap config, and terrain config.

### What Worked

- **Hardening after the UI rewrite was the right shape.** v1002 shipped the redesigned surface; v1003 converted the riskiest flows into browser-backed behavior evidence before adding new capabilities.
- **Playwright MCP complemented automated specs.** The final browser inspection caught the real UI state and console health after the automated smoke, focused tests, lint, and build gates passed.
- **No-migration discipline held.** The milestone proved the new sidebar/modal behavior over existing `Map` and `MapLayer` fields without expanding schema or renderer scope.

### What Was Inefficient

- **The generic milestone completion helper overcounted historical phases.** It treated archived and backlog phases as part of v1003, so archive state needed manual correction to phases 1014-1018.
- **DEM terrain remains hard to prove end-to-end in the browser.** Deterministic component/unit coverage is in place, but a seeded DEM E2E fixture would make future terrain verification stronger.
- **The large map-vendor build warning remains noisy.** It is pre-existing and nonblocking, but it still appears in closeout output.

### Patterns Established

- Run a browser-hardening milestone immediately after high-frequency builder UI rewrites before moving to new renderer or catalog capabilities.
- Treat Kepler.gl as a workflow reference, while keeping GeoLens schema, MapLibre architecture, and component vocabulary unchanged.
- For schema-preserving UI work, pair real-browser specs with round-trip response-key stability tests to prevent accidental model drift.

### Key Lessons

- GSD archive helpers are advisory in this repo; active milestone scope must be manually checked against the intended phase range before committing archive state.
- Add Dataset and Map Stack are now high-value smoke targets. Future builder milestones should preserve the focused modal/sidebar specs as first-class gates.
- Viewer compatibility belongs in builder hardening, not only release validation, because builder-authored basemap and terrain settings are consumed outside the editor.

### Cost Observations

- Model mix: frontier model for planning, implementation, browser verification, audit, and archive correction.
- Sessions: one continuation from v1002 redesign into v1003 hardening and closeout.
- Notable: v1003 kept implementation risk narrow by adding tests and browser evidence around an already-shipped UI instead of adding capability surface.

---

## Milestone: v1000 — Map Stack and Basemap Layer Controls

**Shipped:** 2026-05-11
**Phases:** 2 (1000-1001) | **Plans:** 7 | **Tasks:** 27

### What Was Built

- Unified Map Stack for Surface, Relief, Basemap, Data, Labels, and Interactions.
- Persisted curated `basemap_config` with backend validation, style JSON round-trip, builder controls, public-viewer rendering, OpenAPI, and SDK artifacts.
- Relief/terrain presentation polish that separates DEM elevation surfaces from hillshade/color/contour visual overlays.
- Public viewer parity for basemap appearance across shared-token and authenticated public map paths.
- Authenticated public DEM metadata preservation through `PublicMapViewerPage.toSharedLayer`.

### What Worked

- **Frontend-only model first.** Plan 1000-02 established a pure Map Stack model before the UI and persistence work, which kept saved-map compatibility explicit.
- **Gap closure was small and targeted.** Phase 1001 fixed the authenticated public DEM metadata gap at the conversion boundary without widening the backend or `ViewerMap` contracts.
- **Visual QA matched the feature risk.** Playwright MCP screenshots caught the stack/relief/public-map presentation risk better than DOM-only assertions would have.

### What Was Inefficient

- **Generated SDK drift mixed with milestone output.** Plan 1000-04 regenerated basemap artifacts but also surfaced unrelated `tile_columns` and route-description drift, requiring selective ownership.
- **Visual QA is not durable yet.** Screenshot evidence is recorded, but no automated visual regression gate prevents future stack/public-map presentation drift.
- **Audit found a small test helper issue after feature work.** The `map-stack` helper dropped `basemap_config`; closeout fixed it, but the suite should have been green before audit handoff.

### Patterns Established

- Use a normalized stack model as the source of truth for complex builder surfaces before changing persisted contracts.
- Keep public viewer transforms shared with builder transforms when the rendering semantics must match exactly.
- Preserve optional API metadata during page-level conversion instead of normalizing it away before viewer components receive it.

### Key Lessons

- Completion pre-flight should rerun the exact failed focused suite from the audit before accepting tech debt; the `map-stack` failure was cheap to fix.
- DEM and relief need product language as much as code. Users need to see terrain as an elevation surface and hillshade/contour/color outputs as relief overlays.
- Ignored planning archives are useful local history, but public git commits should stay scoped to tracked closeout state and source/test fixes.

### Cost Observations

- Model mix: frontier model for closeout and verification.
- Sessions: 1 closeout continuation after Phase 1000 and Phase 1001 execution.
- Notable: 35 milestone commits from first Phase 1000 implementation through Phase 1001 DEM fixture coverage.

---

## Milestone: v13.10 — GH Issues Hygiene

**Shipped:** 2026-05-07
**Phases:** 1 (Phase 257) | **Plans:** 3 | **Commits:** 0 (no source-file changes)

### What Was Built

A clean GitHub issue tracker. All 11 open issues in `geolens-io/geolens` (#50-#59 builder issues + #97 sequencing tracker) audited against v13.8 + v13.9 milestone audits, classified CLOSED, and closed on github.com with REQ-ID-citing comments. Tracker #97 closed last with a summary comment listing each child closure path. PROJECT.md `Active`/`Out of Scope`/footer refreshed; `BUILDER-POLISH-01` and `OPS-01` (pre-existing deferred items) explicitly named in PROJECT.md Out of Scope.

### What Worked

- **Single-phase shape for hygiene milestones.** Three plans in strict sequence (audit doc → CTRL-01 gate → tracker refresh) with no parallelism opportunity — splitting into multiple phases would have manufactured artificial boundaries. Right-sized.
- **CTRL-01 single batch confirmation as the only user-input gate.** A table of issue#, verdict, and comment-text-preview presented before the 11 mutations was sufficient consent. Per-issue confirmation would have been needless friction in `/gsd-autonomous` mode.
- **Audit doc as source of truth for closure-comment text.** Plan 01 wrote per-issue closure comments into `257-ISSUE-AUDIT.md`; Plan 02 copied verbatim into `gh issue close --comment` calls. No paraphrase drift; full record of what was claimed when.
- **Existing milestone audit docs as primary authority.** v13.8 + v13.9 MILESTONE-AUDIT.md were already thorough enough to satisfy 8 of 11 issues without code spot-checks; only #51, #56, #58 needed lightweight evidence beyond the audit. Saves work and keeps the verdict-trail high-trust.

### What Was Inefficient

- **`gsd-sdk query roadmap.analyze` returned 6 phases** when only 1 was milestone-scoped (it included 5 999.X backlog phases). Required orchestrator-side filtering. The init JSON's `phase_count: 6` was misleading. Future hygiene milestones may want a backlog-aware filter built into the SDK.
- **`gsd-sdk milestone.complete` produced a sparse MILESTONES.md entry** ("11 CLOSED, 0 LEFTOVER, 0 UNCLEAR." as the sole accomplishment). Hand-edited to richer narrative post-archive. The auto-extraction reads SUMMARY.md `one_liner` fields but the hygiene phase's SUMMARYs didn't have rich one-liners, only verdict counts. Consider richer SUMMARY.md templates for non-feature work.
- **gsd-execute-phase Skill invoked but executed inline.** For a hygiene phase with no code generation, spawning per-plan executor agents was excessive context overhead. Inline execution (~3 minutes total) was the right pragmatic call. The workflow's `--interactive` flag exists for this — could have been used explicitly from the start.

### Patterns Established

- **Hygiene-milestone shape:** 1 phase, N strictly-sequential plans, 0 source-file changes, single batch CTRL-01 gate. Use this when the milestone is "verify + close + refresh tracker" rather than feature work.
- **Closure-comment verbatim copy:** authoring closure comments in the audit doc (Plan 01) and copying to `gh issue close --comment` verbatim (Plan 02) eliminates paraphrase drift and creates a record of intent.
- **REQ-ID-citing closure comments:** every closure comment names the satisfying REQ-IDs and links to the milestone audit doc that satisfies them. Future readers can trace any closed issue back to the milestone that shipped it.

### Key Lessons

- **Ship the audit doc separately from the closures.** Even though Plan 02 could have inlined the verdict logic, separating Plan 01 (verdict) from Plan 02 (mutation) gave the user a clean inspection point at the CTRL-01 gate. The doc becomes the contract; the mutations become bookkeeping.
- **Acknowledge accumulated debt at every milestone close.** The pre-close artifact audit found 177 open items (175 quick_tasks + 2 todos), matching the v13.1/v13.2 standing pattern. Documenting them as deferred at each close keeps the running pool visible without forcing triage on a hygiene milestone.
- **Close stale tracker issues fast.** All 11 issues had been satisfied for ~36 hours (since v13.9 shipped 2026-05-06) but stayed open until v13.10 ran. The cost of leaving an issue tracker stale is opacity for outside readers; closing them with REQ-ID-citing comments is cheap.

### Cost Observations

- Model mix: 100% opus for orchestration; opus for planner; sonnet for plan-checker. No subagent code generation needed.
- Sessions: 1 (single conversation from `/gsd-new-milestone open GH issues` through milestone close).
- Notable: zero source-file changes; entire milestone was markdown writes + 11 `gh issue close` calls.

---

## Milestone: v13.8 — Map Builder Advanced Styling

**Shipped:** 2026-05-06
**Phases:** 6 (246, 247, 248, 249, 250, 251) | **Plans:** 22 | **Commits:** 29 milestone-scoped

### What Was Built

- Clean `paint`/`style_config` boundary with row migration and incremental layer-diff API (`PATCH /maps/{map_id}/layers`) preserving stable layer IDs; full-replacement save retained as fallback.
- First-class raster paint controls (with reset), line gap/blur/offset (with `line-gradient` deferred), zoom expression editor for `step`/`interpolate` stops, and adapter preservation of expression-valued paint.
- DEM hillshade adapter with builder controls; persisted map-level terrain config across builder, public viewer, and shared/embed surfaces with vertical-unit caveats.
- MapLibre style JSON export/import with round-trip for raster, DEM hillshade, terrain block, and outline/extrusion/label companions; sprite-backed symbol/icon layers with upload/storage/serving and consolidated symbol+label adapter.
- Durable map edit history backed by committed-save event capture; builder right-rail History panel matching the established panel system.
- Re-audit passed with 27/27 requirements satisfied at the functional level after commit `e46b96c6` closed NEW-INT-01 (`/maps/import` terrain persistence).

### What Worked

- **Foundation phase ordered first.** Phase 246 separated `paint`/`style_config` and shipped incremental layer save with stable IDs before any advanced styling controls landed. Every subsequent phase relied on the clean boundary, and the diff API made history events reference durable layer identity instead of array indices.
- **Audit re-run caught a real gap.** The first audit identified parser-level fixes that Phase 251 closed. The re-audit then surfaced NEW-INT-01 — a wiring break between Phase 251's parser-level fix and the `/maps/import` HTTP endpoint that was not exercised by any DB-backed test. Catching it with a re-audit (rather than a follow-up bug report) avoided shipping a broken round-trip.
- **TDD on Phase 251 export+import.** Both 251-01 (export) and 251-02 (import) wrote failing tests first, then made them pass. The pre-existing assertions that encoded the bug were updated as part of the GREEN commit, with explicit "deviation auto-fixed" notes — a clean pattern for fixing tests that codified incorrect behavior.
- **Phase 252 was correctly absorbed inline.** The planned paperwork-only Phase 252 (HIST traceability + audit re-run) had its scope folded into Phase 251 + inline reconciliation during the audit re-run. Recognizing that the work was already complete, rather than running a no-op phase, kept the close lean.
- **Hillshade paint allowlist + DEM-source-gated terrain block.** Defensive output: only emit valid hillshade paint keys, and only emit top-level MapLibre `terrain` when the matching DEM source is actually in `sources`. Prevents producing broken style references on export.
- **Same-day kickoff to ship.** Started 2026-05-05 16:44 EDT (Phase 246-01) and finished 2026-05-06 10:39 EDT (Phase 251-02 NEW-INT-01 fix). 22 plans across 6 phases shipped in roughly 18 working hours through tight phase chaining.

### What Was Inefficient

- **Audit-driven phase scaffolding outpaced reality.** Phase 252 was scaffolded as soon as the first audit reported HIST paperwork drift, before observing that the drift could be reconciled inline. The phase ended up being deleted before close. A "wait for audit re-run before scaffolding closure phases" rule would have avoided the planning churn.
- **Phase 249 originally claimed STYLEX-01/02.** The Phase 249 SUMMARY listed STYLEX-01 and STYLEX-02 as completed, but the milestone audit found integration gaps that required reassigning them to Phase 251. Better cross-phase verification at Phase 249 close (export/import round-trip test for raster + DEM + terrain + companions) would have caught this earlier and either kept STYLEX in 249 or made Phase 251 unnecessary.
- **No `VALIDATION.md` for any v13.8 phase.** Nyquist validation is enabled in repo config but was not enforced during v13.8. Carried forward as inherited tech debt.
- **Phase 252 ROADMAP traceability stale.** During the milestone, ROADMAP said "22 complete and 5 pending audit closure" while the traceability table at the bottom said all 27 complete. Two disagreeing counts in the same file — fixed at close, but a reconciliation rule (single source of truth for coverage counts) would prevent it.

### Patterns Established

- **Foundation phase before advanced controls.** When a milestone adds many feature surfaces on top of a shared substrate, ship the substrate cleanup as Phase 1 and require all subsequent phases to consume the new boundary.
- **Audit re-run discipline.** When an audit identifies functional gaps, fix them in a dedicated gap-closure phase, then re-audit. Re-auditing surfaces wiring breaks that focused tests miss (NEW-INT-01 lived between two correctly-tested layers).
- **DB-backed integration tests for HTTP endpoints.** Parser-level dataclass tests are not sufficient for endpoint correctness. Every endpoint that consumes a parsed payload should have at least one DB-backed integration test covering the full request → persist → response cycle.
- **Companion folding into parent's `style_config.builder`.** When importing styles, absorb related companion layers (outline, extrusion, label) into the primary layer's builder block rather than keeping them as separate primaries. `summary.layers_imported` counts only the parent.
- **Canonical-shape detection for foreign imports.** When folding companions whose values were emitted in a specific canonical shape (e.g., `["coalesce", ["to-number", ["get", col], 0], 0]`), only fold on the canonical shape; foreign imports with arbitrary expressions are silently skipped rather than guessed.
- **Existing-key precedence merge.** When two restoration paths can both populate the same builder key, define which one wins ties (here: metadata-restored block wins; companion-derived values fill in only what's absent).

### Key Lessons

1. **Re-audits catch wiring breaks that focused tests miss.** Phase 251's parser-level tests were green, but no DB-backed test exercised the `/maps/import` endpoint, so the parser → endpoint → persist break was invisible. The re-audit's integration check found it; commit `e46b96c6` shipped two DB-backed regression tests as part of the fix.
2. **Cross-phase verification matters at phase close, not just at milestone audit.** Phase 249 self-reported STYLEX-01/02 as complete based on per-plan tests; the milestone audit later found integration gaps. Phase-close verification should include round-trip checks against any other phase's output that consumes the same surface.
3. **Paperwork-only closure phases should be evaluated against current audit status before scaffolding.** Phase 252 ended up unnecessary because the audit re-run reconciled HIST paperwork inline. Defer scaffolding such phases until the audit re-run actually identifies remaining work.
4. **Single source of truth for coverage counts.** When multiple sections in the same file report the same count (REQUIREMENTS table, traceability table, summary line), they will drift unless one is generated from the other. v13.8 had three sources reporting 22 vs 27; reconcile to one or assert equivalence in close audit.
5. **Audit gap-closure phases inherit the audit's resolution mechanics.** Phase 251 was created in response to milestone audit gaps and TDD-ed its way through both export and import; the re-audit then identified one remaining gap (NEW-INT-01) which was closed inline rather than spawning Phase 252-bis. The "audit → fix → re-audit → fix → re-audit-passes" loop is short and effective.

### Cost Observations

- **Model mix:** inherited frontier model for planning, implementation, and audit synthesis.
- **Sessions:** ~6 distinct planning/execution sessions across 2 calendar days (2026-05-05 → 2026-05-06).
- **Notable:** Highest plan-density milestone in this v13.x series (22 plans / 6 phases / 2 days). Style boundary cleanup in Phase 246 paid for itself — every later phase consumed the new `style_config` contract without rework. The Phase 252 fold-in saved one full discuss-plan-execute cycle by recognizing the work was already done.

---

## Milestone: v13.7 — Manifest-Driven Catalog Automation

**Shipped:** 2026-05-04
**Phases:** 5 (241, 242, 243, 244, 245) | **Plans:** 18 | **Commits:** 43 milestone-scoped

### What Was Built
- Versioned `geolens.yaml` manifest schema, validation helpers, good/bad fixtures, and compatibility tests.
- `geolens init` and offline `geolens validate` with deterministic exit codes, path-specific errors, remediation output, and import-boundary guards.
- Backend manifest apply API/service that reuses existing auth, upload permission, storage validation, file safety, ingest jobs, catalog metadata, search, and map-preview behavior.
- `geolens apply` and `--dry-run`, public examples, and a Docker Compose first-catalog walkthrough.
- OpenAPI, Python SDK, TypeScript SDK, CI manifest gates, architecture guards, and a formal close audit covering 19/19 requirements.

### What Worked
- **Schema-first adoption path.** Putting the manifest contract in the CLI package kept local init/validate fast, testable, and independent of backend/runtime services.
- **Reuse of existing ingestion contracts.** Manifest apply stayed small because it routed through existing auth, storage safety, idempotency, and ingest/catalog behavior instead of creating a second ingestion stack.
- **Examples doubled as contract tests.** Public first-catalog examples were validated offline and backed by CLI/API round-trip tests, so docs and behavior moved together.
- **Close gates matched the new surface.** OpenAPI/SDK drift checks, CI manifest gates, and architecture guards covered the API, CLI, generated clients, and Community/Enterprise boundary.

### What Was Inefficient
- **Generic milestone helper remains unsafe for active-plus-archived histories.** `milestone complete` counts every phase directory and even treats `--help` as a version, so v13.7 archival needed manual scoped updates.
- **Phase 245 summary aliases can confuse naive counts.** Index alias summaries are useful for lookup but must be excluded from plan/task counting.
- **Full-suite status is still intentionally separate.** The close audit used focused manifest gates and does not claim unrelated backend/frontend/E2E suite health.

### Patterns Established
- Manifest-style adoption features should ship schema, CLI local validation, backend apply, docs/examples, generated contracts, CI gates, and close audit as one continuous contract.
- Public examples should be validated as tests whenever they are part of the promised adoption path.
- GSD archival in this repo should use active ROADMAP/STATE scope over generic phase-directory counts.

### Key Lessons
1. Keep offline user workflows free of backend, SDK transport, database, GDAL, rasterio, and Enterprise dependencies when they are meant to run before a service exists.
2. Reusing mature service boundaries is the fastest way to add declarative automation without duplicating policy and safety logic.
3. Close audits should clearly separate focused milestone evidence from broader suite health.

### Cost Observations
- Model mix: inherited frontier model for planning, implementation review, audit synthesis, and archival.
- Notable: v13.7 had high leverage relative to diff size because it turned existing catalog capabilities into a declarative first-catalog workflow.

---

## Milestone: v13.6 — Catalog Maps/Search Service Decomposition

**Shipped:** 2026-05-04
**Phases:** 5 (236, 237, 238, 239, 240) | **Plans:** 18 | **Commits:** 40 milestone-scoped

### What Was Built
- `catalog/maps/service.py` is now a thin public facade over focused shared, CRUD, layer, and public/share modules.
- `catalog/search/service.py` is now a thin public facade over focused filter, facet, collection, semantic, dataset, and OGC record modules.
- Architecture guards prevent direct external imports of private maps/search service modules and enforce facade/private module size budgets.
- VRT/search tests now assert helper and facade contracts instead of brittle source-introspection blocks.
- Phase 240 records broader backend/frontend/E2E gate outcomes and closes project-owned Pydantic deprecation warnings.

### What Worked
- **Facade-first decomposition.** Keeping public imports stable let the services split without broad router, AI, OGC/STAC, or test call-site churn.
- **Boundary guards matched the risk.** Private import guards and size budgets protect the exact regression mode this milestone was meant to prevent.
- **Focused close gates stayed high-signal.** Maps/search pytest plus touched-module ruff/format checks proved the owned surface without overstating unrelated full-suite failures.
- **Audit debt was closed before archival.** Phase 240 turned an initial tech-debt audit into a passed milestone audit with exact residual-risk evidence.

### What Was Inefficient
- **Generic GSD counts are still too broad.** The milestone CLI counted archived/backlog history until corrected manually to phases 236-240.
- **Full-suite local readiness remains uneven.** Full backend coverage and Playwright smoke exposed existing blockers outside the maps/search decomposition surface.
- **Warning cleanup mixed local and upstream ownership.** Pydantic warnings were easy local fixes; Alembic/Authlib warnings needed documented owner follow-up instead of risky suppression.

### Patterns Established
- Large service decompositions should land behind stable facade modules with explicit `__all__`, facade export tests, private import guards, and size budgets.
- Source-introspection tests should be replaced with behavior contracts when a refactor changes file layout but not public behavior.
- Broader gate failures outside the owned milestone surface should be documented precisely, not folded into unrelated refactor scope.

### Key Lessons
1. Manual scope validation is required before milestone archival in this repo; helper output is advisory when archives and backlog phases coexist.
2. A thin facade plus architecture guard is the lowest-friction pattern for service decomposition with stable API behavior.
3. Close audits should record exact unowned full-suite blockers while keeping focused owned-surface gates green and repeatable.

### Cost Observations
- Model mix: inherited frontier model for implementation review, audit synthesis, and archival.
- Notable: most code churn was net movement out of two large service files; the durable value is the guardrail suite around future maps/search work.

---

## Milestone: v13.5 — Enterprise Governance Seams

**Shipped:** 2026-05-03
**Phases:** 4 (232, 233, 234, 235) | **Plans:** 13 | **Commits:** 49

### What Was Built
- `PermissionExtension` now covers action checks, catalog visibility filtering, and dataset detail access with a Community default, overlay tests, and a chokepoint architecture guard.
- `WorkflowExtension` now covers publication transitions and transition hooks for `/status/`, `/target-status/`, and metadata `record_status` writes.
- Advanced-sharing gates now line up across schema validators, service guards, builder UI affordances, API/OpenAPI text, and GTM docs.
- Formal close audit verified Seam Quality A, Boundary Integrity A, Inventory Accuracy A−, and no unresolved P0/P1 findings.

### What Worked
- **Single-slot governance seams.** Permission and workflow policy both fit the established typed-accessor pattern, keeping overlay behavior explicit and testable.
- **Architecture guards kept the contract small.** The permission and workflow guards verify the exact chokepoints that would regress the seam, without pretending to prove every future policy surface.
- **Contract verification paid off.** Phase 234 checked schemas, services, UI, OpenAPI, and GTM copy together, preventing paid/free claims from drifting away from actual enforcement.
- **Close audit stayed honest.** Phase 235 separated seam readiness from future product UI scope and did not claim unrun full-suite coverage.

### What Was Inefficient
- **GSD milestone helpers misread this repo shape.** `init milestone-op` reported `v1.0`, and the generic milestone CLI counted archived/backlog phases. The close path needed manual scoping to phases 232-235.
- **Local DB provisioning remains uneven.** Some phase checks needed `POSTGRES_PORT=5434` or DB-provisioning bypasses because the default reachable database lacked PostGIS/pgvector.
- **Plan artifacts remain ignored by default.** `.planning/` archival files require intentional force-adds, which is easy to miss at milestone close.

### Patterns Established
- Governance seams should ship with Protocol + default + typed accessor + production chokepoint routing + overlay test + architecture guard.
- Paid/free product contracts need dual-layer enforcement (schema + service) plus UI and OpenAPI/GTM copy review.
- Formal milestone audits should explicitly note any tool-scoping anomalies rather than let helper output drive archive scope.

### Key Lessons
1. Treat GSD helper output as advisory when old archives and backlog phases are present; use `STATE.md` and the active ROADMAP section as the source of truth.
2. For open-core seams, "Ready" means a real overlay can alter behavior without core changes and a guard catches known bypasses.
3. Keep focused close-audit evidence separate from full-suite readiness, especially when local DB provisioning differs from CI.

### Cost Observations
- Model mix: inherited frontier model for planning and audit synthesis; Sonnet-class helper configuration noted by GSD tooling but not used for a spawned checker.
- Notable: same-day milestone with a low file count compared to v13.4, but high leverage because it closed two governance seams and the advanced-sharing product contract.

---

## Milestone: v13.4 — Boundary Closeout

**Shipped:** 2026-05-03
**Phases:** 7 (225, 226, 227, 228, 230, 231, 229) | **Plans:** 23 | **Commits:** 170

### What Was Built
- `ProcessingPort` and `CatalogPort` now invert both directions of the catalog/processing dependency cycle.
- `AIProviderExtension` and `EmbeddingProviderExtension` make chat/completion and embeddings provider dispatch extensible.
- SAML overlay tests write generated fixture output to temporary paths instead of mutating committed fixtures.
- Cold publish workflows verified public registry artifacts: `geolens`, `geolens-cli`, and `@geolens/sdk` at `1.0.0`.
- Post-implementation close gate produced `post-impl-20260503-v13-4.md` with Boundary Integrity A+, Coupling Health A−, Seam Quality A−.

### What Worked
- **Symmetric boundary ports.** Phase 225's `ProcessingPort` pattern was reusable for Phase 230's `CatalogPort`, making the second half of the cycle inversion faster and more auditable.
- **Architecture guards carried the milestone.** Bidirectional catalog/processing import guards plus provider-SDK import guards gave simple evidence for the close audit.
- **Cold publish verification closed an external blocker.** Phase 228 turned package workflows from wired-but-cold into verified public registry artifacts.
- **Post-impl audit fixed real P1s inline.** Format drift and stale test patch targets were caught and fixed before close.

### What Was Inefficient
- **The milestone roster changed midstream.** Phase 230 and 231 were promoted after the 2026-05-02 audit, which meant state/roadmap tools sometimes misidentified backlog `999.*` work as next.
- **Local DB provisioning still limits full-suite signal.** Host Postgres without pgvector forced focused checks or Compose-specific env usage.
- **Dirty unrelated work affected full-suite audit evidence.** In-progress advanced-sharing changes caused one embed-token failure during Phase 229 until stashed before archival.

### Patterns Established
- Protocol seams should ship with a default adapter, registry accessor, focused seam tests, and an architecture guard in the same phase.
- Post-impl close gates should treat local dirty worktree changes as residual risk unless they are part of the committed milestone surface.
- For open-core feature gates, schema validators and service-layer checks should agree.

### Key Lessons
1. Promote audit-discovered backlog items into the active milestone only after updating both roadmap and state, otherwise transition tooling can point at backlog phases.
2. Keep milestone-close tags on a clean worktree; stash unrelated in-progress work before archival.
3. Full-suite claims need a stable local PostGIS + pgvector database, otherwise reports should use focused checks and document the environment gap.

### Cost Observations
- Model mix: planner/executor agents used inherited frontier model for hard refactors; Sonnet-class agents handled research/checking.
- Notable: 7 phases in 3 days, with generated/publication artifacts contributing heavily to file count.

---

## Milestone: v13.1 — Open-Core Separation P1

**Shipped:** 2026-04-29
**Phases:** 8 (212–219) | **Plans:** 30 | **Commits:** 179

### What Was Built
- Open-core boundary closed: `core/` no longer reaches into `modules/settings/`; `auth/visibility.py` relocated to `catalog/authorization.py`; broadened architecture-guard test prevents regression.
- `IdentityProtocol` extracted in `core/identity.py`; 51 cross-domain `User` import sites retyped to `Identity`; `get_identity_extension()` hook lets enterprise overlays register custom identity backends.
- Auto-generated SDKs (Python via `openapi-python-client`, TypeScript via `@hey-api/openapi-ts`); `make sdks` regen one-shot; `make sdks-check` CI drift gate; `flatten_openapi_defs.py` preprocessor for OpenAPI 3.1 inline `$defs`.
- Apache-2.0 `geolens` CLI on PyPI: `login` (keyring + headless), `scan`, `publish`, `export stac` — consumes only the generated Python SDK; CI grep + tomllib gates enforce zero hand-rolled HTTP.
- SAML enterprise overlay: `geolens-enterprise` registers via `importlib.metadata` entry_points with dual `AuthExtension` + `IdentityExtension` Protocol seams; SP-initiated SSO + JIT provisioning + audited attribute→role mapping; admin UI 3-layer gated.
- Closing audit produced (Phase 218) and remediated (Phase 219) — OAuth IdP→role mapping P0 surfaced by audit closed via `is_enterprise()` schema + service gate; audit doc amended in place from BLOCKED → VERIFIED.

### What Worked
- **Architecture-guard tests as forcing functions.** Phase 212 added a settings-only guard; Phase 214 broadened it to a general core/-imports guard with an 18-file allowlist. Each refactor phase shipped its guard before merging — making layering invariants enforceable at CI time, not just review time.
- **Phase 219 added mid-milestone to close a P0.** Phase 218's audit surfaced an architectural P0 (OAuth IdP→role mapping in core) that hadn't been on the milestone plan. Adding Phase 219 to fix it (rather than waving the audit) preserved the boundary contract and kept the milestone's audit-grade promise intact.
- **Pitfall-driven planning.** Phase 217 caught a HIGH-severity ORM column-not-found risk before merge by empirically testing `deferred=True` mitigation (Pitfall 11) — saved a likely production outage path.
- **Round-trip tests over unit-test theater.** Phases 215 and 216 invested in real cross-process integration tests (uvicorn-on-free-port + CliRunner via `asyncio.to_thread`; both SDKs against live FastAPI app) rather than mocking. 12 SDK + 6 CLI round-trip tests give meaningful signal.
- **Carve-outs documented as intentional.** Phase 217 SC#1 (`git grep -i saml` returns zero matches in core) explicitly carved out 5 files of Pitfall 11 mitigation scaffolding. Documenting "carve-out, not violation" in module headers + SUMMARY + audit doc avoids future "why is this here?" cycles.

### What Was Inefficient
- **Paperwork drift across 4 phases.** Phases 214, 215, 217, 218 shipped with per-plan verification gates passing but no consolidated phase-level VERIFICATION.md. Required a separate paperwork close pass at milestone end; the `gsd-audit-milestone` audit returned `tech_debt` because of artifact gaps, not functional ones. Lesson: produce phase-level VERIFICATION.md at phase-close time, not aggregated retroactively.
- **REQUIREMENTS.md traceability lag.** SAML-08..12 + AUDIT-V1 stayed `[ ]` despite all five SCs verified — checkboxes were never flipped at phase-close. Same paperwork cause as above; same fix.
- **VALIDATION.md status drift.** 6/8 phases shipped with `status: draft / nyquist_compliant: false` because `/gsd-validate-phase` was never run as a closing step. The framing turned out to be honest ("paperwork only — green test baseline already covers"), but the field was misleading.
- **170 quick_tasks accumulated as cross-milestone backlog.** Spans 2026-03-16 → 2026-04-26 (v10.x–v13.0 era). Should have been triaged via `/gsd-cleanup` between milestones; now a hygiene debt that has to be cleared eventually.
- **Audit parser produced false-positive on OCCLI-02 frontmatter.** The audit reported "216-02-SUMMARY.md is `[]`" for `requirements:` — but the SUMMARY format uses `tags:` (which already contained `occli-02`). Lost a few minutes confirming the audit was wrong; the auditor's field-name expectation didn't match the SUMMARY convention.

### Patterns Established
- **Per-phase verification gate plan as the last plan of every phase.** Phase 214's Plan 04, Phase 215's Plan 05, Phase 217's Plan 05, Phase 218's Plan 01 all followed this pattern — explicit "verify all SCs" plan with its own SUMMARY. This pattern made phase-level VERIFICATION.md trivially aggregatable when finally produced.
- **`/gsd-plan-milestone-gaps` paperwork-close path.** When the audit returns `tech_debt` due to artifact gaps (not functional gaps), skip phase creation and edit directly. Documented in this retrospective so future milestones with the same shape know they have a fast-path.
- **`is_enterprise()` runtime gate at schema validator + service entry.** Phase 219 established the canonical pattern for community/enterprise feature gates: `model_validator(mode='after')` raises `ValueError` in community; service-layer code checks `is_enterprise()` before applying enterprise-only logic. Both layers must agree — schema-only gating leaves drift, service-only gating leaks via bulk import paths.
- **Audit doc amend-in-place over re-issue.** Phase 219 amended `oc-separation-audit-v13.1-close.md` in place (BLOCKED banner replaced with VERIFIED; pre-remediation state preserved as `### Pre-remediation state (2026-04-29)` subsection). Better than issuing a new audit document — single canonical artifact, audit-trail preserved.

### Key Lessons
1. **Run phase-close paperwork as part of phase-close, not milestone-close.** Phase-level VERIFICATION.md, REQUIREMENTS.md checkbox flip, VALIDATION.md formalization should all happen at phase-close. Milestone-close should be archival, not paperwork triage.
2. **A failed audit isn't a milestone block — it's signal.** Phase 218 BLOCKED on Boundary Integrity B− vs A− target, surfacing the OAuth IdP→role mapping P0. Adding Phase 219 mid-milestone closed the cluster and preserved the milestone-close promise. The instinct to "wave the audit" is wrong; the audit is doing its job.
3. **Scaffolding documented as carve-out is fine; scaffolding hidden in core is debt.** SAML's deferred=True ORM scaffolding in 5 core files is documented carve-out from SC#1. The pattern is: be honest about boundary violations and document them with rationale, vs. pretending the boundary is clean when it isn't.
4. **Cross-milestone hygiene needs an explicit cadence.** 170 accumulated quick_tasks is a hygiene debt that should have been resolved across milestones. Add `/gsd-cleanup` to the milestone-close ritual.

### Cost Observations
- Model mix: predominantly Opus 4.7 for planning + execution; Sonnet for parallel research/integration-check agents
- Notable: 4-day milestone with 8 phases (avg 12hr/phase wall-clock); generated SDK code (655 files, 112k LOC) was the largest line-count contribution, but the architectural work (10k LOC hand-written across boundary refactor + identity protocol + SAML overlay) was the substantive change.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Key Change |
|-----------|--------|------------|
| v13.7 | 5 (241, 242, 243, 244, 245) | Manifest-driven catalog automation; offline CLI init/validate; backend apply ingestion; generated contract and CI gates |
| v13.6 | 5 (236, 237, 238, 239, 240) | Maps/search service decomposition behind stable facades; private-module import and size-budget guards; audit debt closed |
| v13.5 | 4 (232, 233, 234, 235) | Governance seams for permissions and workflows; advanced-sharing contract aligned across schema/service/UI/API/GTM; close gate at A/A/A− |
| v13.4 | 7 (225, 226, 227, 228, 230, 231, 229) | Symmetric Protocol boundaries for catalog/processing; AI + embeddings provider seams; post-impl close gate with A+/A−/A− grades |
| v13.1 | 8 (212–219) | Architecture-guard tests as CI-enforced layering invariants; mid-milestone phase additions to close audit-surfaced P0s; per-phase verification gate plan as standard pattern |

### Cumulative Quality

| Milestone | Backend Tests | Notable |
|-----------|---------------|---------|
| v13.7 | Focused manifest CLI/backend/schema/example/boundary tests, OpenAPI check, SDK drift checks, CI manifest gates, and close audit green; full backend/frontend/E2E not claimed | Declarative first-catalog workflow is now covered from schema through CLI, API, SDKs, docs, and architecture guards |
| v13.6 | Focused maps/search pytest, touched-module ruff/format checks, frontend build/lint/coverage green; full backend/Playwright blockers documented | Maps/search facades are stable and guarded; project-owned Pydantic deprecation warnings fixed |
| v13.5 | Focused permission/workflow architecture guards, advanced-sharing DB-backed tests, frontend sharing tests, and OpenAPI check green; full-suite not rerun | PermissionExtension and WorkflowExtension now rated Ready; advanced-sharing paid/free contract is enforced and documented |
| v13.4 | Focused architecture/provider/reupload checks green; full-suite limited by local DB/dirty-worktree constraints | Bidirectional import guards and provider-SDK guards now enforce open-core boundaries |
| v13.1 | 1999+ pass (baseline maintained throughout) | 12 SDK round-trip + 9 SAML integration + 9 enterprise + 112 CLI unit + 6 CLI round-trip new |

### Top Lessons (Verified Across Milestones)

1. Architecture guard tests are the strongest close-gate evidence for boundary milestones.
2. Post-impl audits should fix P1s inline before milestone archival.
3. Keep the worktree clean before milestone tags; stash unrelated WIP explicitly.
4. GSD milestone helpers need manual scope validation in repos with archived and backlog phase history.
5. Public examples should be validated as tests when they are part of an adoption promise.
