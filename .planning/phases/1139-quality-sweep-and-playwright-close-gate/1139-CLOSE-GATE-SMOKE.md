---
phase: 1139
driver: orchestrator (mcp__playwright__*)
date: 2026-05-28
canonical_map: c39be324-6815-40e5-8143-00a2723827b2
viewports: [1440x900, 800x600, 414x896]
ai_disabled_test: runtime DB toggle (AI_ENABLED via PATCH /admin/ai-status/) — reversible, no env change
---

# Phase 1139 — Canonical Close-Gate Live MCP Smoke (Orchestrator-Driven)

## QA-01 — 3-Viewport Smoke (zero console errors per viewport)

| Viewport | Map render | Layer op | NavControl top-left | Horizontal overflow | Console errors |
|----------|------------|----------|---------------------|---------------------|----------------|
| 1440×900 | PASS (canvas + 6 layers) | PASS (visibility toggle off→on for NHD streams) | PASS (top=129 left=340) | none | **0** |
| 800×600 | PASS (canvas) | PASS (RasterEditor 7 sliders verified in 1138 re-check) | PASS (top=129 left=64) | none (scrollWidth=800) | **0** |
| 414×896 | PASS (canvas) | PASS (mobile rail: Settings/Add data/Notes/History/Ask AI) | PASS (top=129 left=64) | none (scrollWidth=414) | **0** |

**QA-01 VERDICT: PASS** — all 3 viewports render, layer ops work, NavigationControl stays top-left at every width, no horizontal overflow, zero browser-console errors.

## QA-02 — Disabled-AI Smoke

**Mechanism:** Runtime DB toggle `AI_ENABLED` via `PATCH /api/admin/ai-status/` (reversible — no env edit, no container restart). Before: `enabled: true`. Toggled to `false`, reloaded builder, verified, then restored to `true`.

| Check | Observation | Verdict |
|-------|-------------|---------|
| AI rail button when disabled | Rail shows `"AI unavailable"` button (NOT "Ask AI", NOT an inert button) | PASS |
| Disabled-state actionable | Clicking "AI unavailable" surfaces: **"AI is disabled — An administrator has disabled AI for this instance."** + **"Go to Settings"** CTA | PASS (actionable, not a dead-end) |
| `/ai/*` console errors | 0 errors during disabled-AI flow | PASS |
| Broken-canvas state | Map canvas renders normally; AI disablement does not break the map | PASS |
| Restore | `enabled: true` re-applied; reload confirms rail returns to "Ask AI" | PASS — stack left in correct enabled state |

**QA-02 VERDICT: PASS** — disabled AI surfaces the env_disabled reason (Phase 1135 AIDisabledState contract) with Settings CTA, zero console errors, no broken canvas. AI restored to enabled post-test.

## QA-03 — Deterministic Quality Gates (from Plan 1139-01)

| Gate | Result |
|------|--------|
| typecheck | exit 0 |
| vitest | 2486/2486 PASS |
| lint | 0 errors |
| e2e:smoke:builder | 26/26 PASS |
| test:i18n | PASS |
| check:i18n:changed | PASS |

7 inline fixes applied during gate run (latent issues from in-flight v1030 work). **QA-03 VERDICT: GREEN.**

## QA-04 — CHANGELOG + OpenAPI/SDK (from Plan 1139-02)

- CHANGELOG `[Unreleased]` populated with v1030 measured numbers across all 6 phases.
- **Pitfall #15 caught real drift:** `GET /maps/{map_id}/access/` + `MapAccessResponse` (added in `3ed5ceb3`, never snapshotted) surfaced by `make openapi` (136-line diff). Snapshot + SDKs regenerated; `make openapi-check` + `make sdks-check` both exit 0. CHANGELOG bullet added.
- Downstream: sibling docs repo needs `npm run fetch-openapi` before next deploy (noted in 1139-OPENAPI-DECISION.md).

**QA-04 VERDICT: SATISFIED.**

## Carried-Forward Items From Prior MCP Verifies — Disposition

| Source | Item | Disposition |
|--------|------|-------------|
| 1135 verifier | AI staging tray live (add/reject byte-equal) | Unit-pinned (chat-action-staging.test.ts 11 cases); live requires AI prompt — accepted via pins |
| 1135 verifier | inline data card live | Unit-pinned + backend fix 4b643bde + test_collect_chat_action.py |
| 1137 verifier | chip input / expiration / iframe (enterprise-gated) | Community runtime hides these by design (canUseAdvancedSharing=isEnterprise); unit-pinned for enterprise |
| 1138 verifier | popup media live / empty-filter live | Unit-pinned (36 + 14 cases); RasterEditor regression re-checked live at 800px |

## Pre-Existing e2e Failures (NOT regressions)

`accessibility.spec.ts:151` + `builder-unified-stack.spec.ts:193` are OUTSIDE the e2e:smoke:builder subset and reproduce on 736cffca — not v1030 regressions. e2e:smoke:builder ran fully green (26/26).

## Post-Verification Addendum — Final-State Layer Ops + Save-Persist + Shared/Embed Parity

The phase verifier flagged 2 SC-1 sub-items as needing final-state confirmation (last verified pre-1138). Closed live:

| Item | Test | Verdict |
|------|------|---------|
| Save-persist across reload | Toggled "Land classification" visibility OFF (aria-pressed=false) → Ctrl+S → full reload → still OFF (persisted) → toggled back ON → Ctrl+S → confirmed restored. Canonical ADK map left in original state (all 6 layers visible). | PASS |
| Visibility-toggle layer op (final state) | Covered by the save-persist flow above + NHD streams toggle at 1440×900 earlier. | PASS |
| Shared/embed parity (post-1138) | `/m/{token}?embed=true` after Phase 1138's FeaturePopup changes: map canvas renders, "Powered by GeoLens" branding present, 0 console errors. | PASS |

**Note:** Did NOT permanently delete a layer from the canonical ADK map (it is a curated/shippable marketing map). Delete-layer is exhaustively unit-pinned (builder-layer-mutations.test.ts 12 cases + use-builder-layers.delete.test.ts 5 cases) and was live-verified in Phase 1134's close-gate; the intervening phases did not touch `dispatchLayerAction`/`use-builder-layers.ts` (confirmed: BuilderLayerAction union unchanged across all v1030 commits).

## Final Close-Gate Verdict

**v1030 CLOSE-GATE: PASS**

- QA-01 (3-viewport live MCP): PASS — 0 console errors × 3 viewports
- QA-02 (disabled-AI smoke): PASS — actionable disabled state, AI restored
- QA-03 (quality gates): GREEN — typecheck/vitest 2486/lint/e2e 26/i18n all pass
- QA-04 (CHANGELOG + OpenAPI/SDK): SATISFIED — Pitfall #15 drift caught + fixed

## Stack State

- Frontend: http://localhost:8080 (healthy)
- API: http://localhost:8001 (healthy)
- Postgres / Titiler / Worker: healthy
- Edition: community
- AI: enabled (restored after QA-02 test)
- Branch: codex/builder-polish-walkthrough at 6ad98197 + subsequent
