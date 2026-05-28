---
phase: 1144
phase_name: Contour Spike
status: passed
verified: 2026-05-28
requirements: [CONTOUR-01]
method: orchestrator-driven Playwright MCP (live builder) + dependency analysis
---

# Phase 1144 Verification — Contour Spike

**Status: passed** — all 3 success criteria met. Audit-only phase; no production code changed (temp `CONTOUR_CONTROL_ENABLED` flip reverted, `git diff` clean, repro never saved).

## Success Criteria

1. **~28 MapLibre error events reproduced live + inventoried by category** — ✅
   Deterministic **28 errors + 28 warnings per contour-enable** on map `8dd6a129…` at z14, reproduced twice (28→56). Baseline 0; post-revert 0. Inventoried as a single category: malformed contour-tile `Request` (one per viewport tile). All HTTP was 200/204 — not a fetch/auth/404 failure.

2. **Worker/isoline/`addProtocol` path analyzed; root cause identified (distinct from `716b1927`)** — ✅
   Root cause: `maplibre-contour@0.1.0` emits `dem1-contour://{z}/{x}/{y}` custom-protocol tile URLs that **maplibre-gl 5.24.0 does not route through the registered `addProtocol` handler** — it resolves them as relative HTTP URLs against the origin (`http://localhost:8080dem1-contour://…`), failing `new Request()`. The `716b1927` Map-instance fix is present and correct; the remaining fault is the v5 protocol/worker-source-loading incompatibility.

3. **`.planning/audits/CONTOUR-WORKER-v1032.md` exists with harden-or-cut recommendation + effort estimate** — ✅
   Recommendation: **CUT**. Harden is not "clearly cheap" — `maplibre-contour@0.1.0` is the **latest published version** (no compatible upgrade), declares no maplibre-gl peer dep, and is dormant; hardening = fork/patch or reimplement.

## Disposition handed to Phase 1145

**CUT** the contour control: remove dep + `contour-sync.ts` + call site + flag/gate + 5 dormant tests; add a positive regression pin.

## Human verification needed

None — reproduction and root cause were established live by the orchestrator.
