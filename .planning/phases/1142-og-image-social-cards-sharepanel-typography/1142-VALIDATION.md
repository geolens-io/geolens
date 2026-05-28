---
phase: 1142
slug: og-image-social-cards-sharepanel-typography
status: draft
nyquist_compliant: false
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

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 1142-01-xx | 01 | 1 | SHARE-08 | T-1142-01 | card route escapes/validates token; meta uses absolute URLs; serves only public/shared maps (no private leak) | unit | `cd backend && uv run pytest -k "card or og_image"` | ❌ W0 | ⬜ pending |
| 1142-02-xx | 02 | 2 | SHARE-08 | — | OG capture reuses one repaint; no oversized payload past route cap | unit | `cd frontend && npx vitest run` | ❌ W0 | ⬜ pending |
| 1142-03-xx | 03 | 2 | SHARE-10 | — | N/A (cosmetic) | unit | `cd frontend && npx vitest run src/components/builder/__tests__/SharePanel.test.tsx` | ❌ W0 | ⬜ pending |

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

- [ ] All tasks have automated verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
