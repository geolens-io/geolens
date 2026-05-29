---
phase: 1144
phase_name: Contour Spike
status: complete
requirements: [CONTOUR-01]
completed: 2026-05-28
---

# Phase 1144 Summary — Contour Spike

**Audit-only phase (no production code).** Reproduced and root-caused the deferred contour control's worker instability via orchestrator-driven Playwright MCP, then recommended a disposition.

## What was done

- Reproduced the **deterministic 28-error / 28-warning** burst on contour-enable (live builder map `8dd6a129…`, z14), twice.
- Captured the exact error via a console-warn intercept: `Failed to construct 'Request': Failed to parse URL from http://localhost:8080dem1-contour://14/4830/5949?...`.
- Confirmed via network log that **all HTTP was 200/204** — ruling out fetch/auth/404/encoding causes.
- Confirmed `maplibre-contour@0.1.0` is the **terminal published version** with no maplibre-gl peer dep.
- Wrote `.planning/audits/CONTOUR-WORKER-v1032.md` (error inventory, root cause, harden-vs-cut, effort).

## Root cause (one line)

`maplibre-contour@0.1.0` custom-protocol (`dem1-contour://`) tile URLs are not routed by maplibre-gl 5.x's source loader → resolved as relative HTTP → malformed `Request` → one error per viewport tile.

## Disposition → Phase 1145

**CUT** (harden not clearly cheap; no upstream fix; contour is nice-to-have).

## Artifacts

- `.planning/audits/CONTOUR-WORKER-v1032.md`
- Temp `CONTOUR_CONTROL_ENABLED` flip reverted (git clean); repro never persisted (DB verified).
