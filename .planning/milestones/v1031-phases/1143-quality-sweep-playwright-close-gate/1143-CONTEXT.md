# Phase 1143: Quality Sweep & Playwright Close-Gate - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped). Close-gate phase — verification sweep, not feature dev.

<domain>
## Phase Boundary

The canonical v1031 close-gate (mirrors v1027/v1028/v1029/v1030). Three requirements:
- **QA-01** — intensive live Playwright MCP smoke of the builder against `http://localhost:8080/maps/8dd6a129-8eb0-4ba9-b421-716c83b160dd`, exercising each new control from Phases 1140–1142 and the share/OG flow, with committed evidence. **Orchestrator-driven** (GSD subagents lack `mcp__playwright__*`). This closes the `human_needed` live-render items deferred from 1140 (contour/hypsometric/colormap render), 1141 (fill-pattern set/clear), 1142 (OG card meta + image).
- **QA-02** — touched-surface gates green: frontend `typecheck` + `lint` + `vitest` (`npm run test`), backend `pytest` (focused on touched modules; DB up on 5434, `.env.test` recipe), the e2e smoke (locate the builder smoke script — likely repo-root or an `e2e/` workspace), and i18n parity (`npm run test:i18n`).
- **QA-03** — CHANGELOG v1031 entry; OpenAPI + Python/TS SDK regenerated where backend routes/schema changed: `make openapi` then `make sdks` (1140 added raster `colormap_name`/`stretch` params + `band_count` on MapLayerResponse; 1142 added `PUT`/`GET /maps/{id}/og-image/` + `MapResponse.og_image_url`). The `/card` route is `include_in_schema=False` (no OpenAPI delta). Sibling docs `npm run fetch-openapi` is a post-deploy step in the getgeolens.com repo — NOT run here (note in SUMMARY).

</domain>

<decisions>
## Implementation Decisions

- **Sequencing:** QA-03 OpenAPI/SDK regen must run AFTER all 1140/1142 backend changes (they are done). Run `make openapi` BEFORE `make sdks` (sdks reads openapi.json). Commit regenerated artifacts.
- **QA-02 gate order:** typecheck → lint → frontend vitest → backend pytest → e2e smoke → i18n. Capture concise pass/fail per gate. Pre-existing unrelated failures (if any) must be distinguished from v1031 regressions (v1011 documented some pre-existing e2e flakes — note, do not block on known-pre-existing).
- **QA-01 is orchestrator-only:** the executor does QA-02 + QA-03; the orchestrator drives the live Playwright MCP smoke and writes the evidence file `1143-MCP-SMOKE.md`.
- No new features. No architecture changes. This phase only regenerates artifacts, runs gates, writes CHANGELOG, and verifies live.

</decisions>

<code_context>
## Commands (verified)
- `make openapi` (regen backend/openapi.json), `make openapi-check`; `make sdks` (regen Python+TS SDKs), `make sdks-check`.
- Frontend (`cd frontend`): `npm run typecheck`, `npm run lint`, `npm run test`, `npm run test:i18n`.
- Backend: `cd backend && set -a && source ../.env.test && set +a && uv run pytest -n 4 ...`.
- e2e smoke: locate the builder smoke script (not in frontend/package.json scripts — check repo-root package.json or e2e/ dir).

</code_context>

<specifics>
## QA-01 live MCP checklist (orchestrator runs against the target map)
1. **1140 contour (DEM-04):** on a DEM/terrain layer, toggle CONTOUR LINES; change interval; confirm contour lines render + update on the canvas.
2. **1140 hypsometric (DEM-05):** in hillshade mode, enable HYPSOMETRIC TINT, pick a ramp; confirm elevation banding renders; confirm terrain mode shows the hint only.
3. **1140 colormap (RASTER-COLORMAP):** on a single-band raster layer, pick a colormap; confirm tiles re-render with the colormap (and multi-band shows no section).
4. **1141 fill-pattern (FILL-01):** on a polygon/fill layer, pick a built-in pattern; confirm it renders; clear to None → solid fill.
5. **1142 OG card (SHARE-08):** fetch `/api/maps/shared/{token}/card` for the map's share token; assert og:image + twitter:card meta with an absolute URL; GET the og-image after a save returns a valid image.
6. Console/network hygiene: no new errors in the builder.

</specifics>

<deferred>
## Deferred
- Sibling-repo `npm run fetch-openapi` (getgeolens.com) — post-deploy, not this phase.
- Real-client social unfurl (Twitter/X validator) — external spot-check, noted but not gating.

</deferred>
