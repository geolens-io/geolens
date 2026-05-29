---
phase: 1142
slug: og-image-social-cards-sharepanel-typography
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-28
---

# Phase 1142 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (backend: card route + og-image routes + migration) + vitest (frontend: OG capture wiring + SharePanel) |
| **Config file** | `backend/pytest.ini` (+ `.env.test`) ; `frontend/vitest.config.ts` |
| **Quick run command** | focused: `cd backend && set -a && source ../.env.test && set +a && uv run pytest -n 4 backend/tests/<og/card tests> -q` ; `cd frontend && npx vitest run <SharePanel + capture globs>` |
| **Full suite command** | `cd frontend && npm run test` ; backend focused pytest on touched modules |
| **Estimated runtime** | backend focused ~30–60s ; frontend focused ~10–30s |

---

## Sampling Rate

- **After every task commit:** focused test for the touched surface (backend pytest for routes/migration; vitest for frontend).
- **After every plan wave:** full frontend vitest + focused backend pytest.
- **Before verification:** typecheck clean; touched pytest + vitest green.
- **Max feedback latency:** ~60s.

---

## Per-Task Verification Map

> Populated by the planner / executor. SHARE-08 (card route + og-image routes + capture) gets backend pytest + frontend vitest; SHARE-10 is a CSS-class change with a SharePanel render assertion.

> Final structure: 2 plans. Plan 01 = backend (Wave 1, autonomous); Plan 02 = frontend (Wave 2, depends on 01) with SHARE-10 folded in as Task 3 (shared `SharePanel.tsx` ownership → no parallel split).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 1142-01-T1 | 01 | 1 | SHARE-08 | T-1142-04 | OgImageUploadRequest 750KB cap; ThumbnailUploadRequest 100KB cap unchanged; migration 0024 up/down | unit | `cd backend && uv run pytest tests/test_maps_og_image.py -x -q` | created in plan | ⬜ pending |
| 1142-01-T2 | 01 | 1 | SHARE-08 | T-1142-03, T-1142-05 | og-image PUT owner-only + PIL verify; GET public cache-control; non-owner 403; non-image 400 | unit | `cd backend && uv run pytest tests/test_maps_og_image.py -x -q -k og_image` | created in plan | ⬜ pending |
| 1142-01-T3 | 01 | 1 | SHARE-08 | T-1142-01, T-1142-02, T-1142-06 | card route html.escape (no markup inject); public-only token gate (no private leak); absolute og:image URL | unit | `cd backend && uv run pytest tests/test_maps_og_image.py -x -q` | created in plan | ⬜ pending |
| 1142-02-T1 | 02 | 2 | SHARE-08 | T-1142-08 | 1200×630 capture in ONE repaint (no double-trigger); OG failure isolated from thumbnail | unit | `cd frontend && npx vitest run src/components/builder/hooks/__tests__/use-builder-save.test.ts` | created in plan | ⬜ pending |
| 1142-02-T2 | 02 | 2 | SHARE-08 | T-1142-07 | Copy Link emits `/card` URL; `/m` viewer + embed iframe src unchanged | unit | `cd frontend && npx vitest run src/components/builder/__tests__/SharePanel.test.tsx` | created in plan | ⬜ pending |
| 1142-02-T3 | 02 | 2 | SHARE-10 | — | N/A (cosmetic — 2 explicit font weights, 0 font-bold) | unit | `cd frontend && npx vitest run src/components/builder/__tests__/SharePanel.test.tsx` | created in plan | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Backend: focused tests for `GET /api/maps/shared/{token}/card` (HTML meta correctness, absolute URLs, token validation, public/shared-only access) + `PUT`/`GET /maps/{id}/og-image/` + migration `0024` applies.
- [ ] Frontend: tests for the 1200×630 OG capture wiring in `doCapture` + the Copy-Link URL emission.
- [ ] Existing pytest + vitest infra otherwise covers this phase.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Social card actually unfurls in a real client | SHARE-08 | Requires a 3rd-party crawler (Twitter/X, Slack, iMessage) fetching the live URL | Validate the card HTML + absolute og:image via curl/automated; real-client unfurl is a spot-check at/after the 1143 close-gate (Playwright MCP can fetch the /card route and assert the meta tags + image URL resolve) |
| OG image visually correct (1200×630 map preview) | SHARE-08 | Live WebGL capture | 1143 Playwright MCP — capture + GET og-image returns a valid 1200×630 image |

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test files created within plan tasks)
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-28 (planner)
