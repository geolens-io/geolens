# Phase 1032 Summary

Phase 1032 completed the v1007 release hygiene closeout after v1006 large dataset cluster scaling.

## Completed

- Verified GitHub Dependabot alerts #36 and #37 for `urllib3` against the checked-in backend dependency state. `backend/pyproject.toml` requires `urllib3>=2.7.0`, `backend/uv.lock` contains `urllib3==2.7.0`, `uv lock --upgrade-package urllib3` produced no lockfile change, and `pip-audit --strict --desc` reported no known vulnerabilities.
- Ran the broad release gate set across backend, frontend, security, and browser checks.
- Regenerated `backend/openapi.json` to include the v1006 server-side cluster tile route.
- Regenerated Python and TypeScript SDK artifacts for the cluster tile route and the existing shared-layer `id` response field.
- Fixed the frontend Docker Compose healthcheck from `localhost:5173` to `127.0.0.1:5173`, matching the IPv4 Vite listener and making `docker compose up -d --wait` reliable locally.
- Fixed `e2e/collections.spec.ts` so the Add Dataset collection smoke flow self-seeds and cleans up a tiny fixture dataset instead of relying on Natural Earth or thematic demo seed data.
- Cleaned authenticated temp data that was polluting search results and causing quicklook 404 console errors: the smoke-created `sample` dataset and the v1006 `Cluster UAT Large Points 1778621648562` dataset. The v1006 map was already absent.
- Verified the live app via Playwright MCP after cleanup: authenticated search rendered 3 results and the current page had 0 warnings and 0 errors.

## Requirements

- REL-01 complete: Dependabot alerts were checked against manifests, lockfile, and `pip-audit`; local state is patched and scanner-clean. Follow-up on 2026-05-12 dismissed stale GitHub alerts #36/#37 as inaccurate with the same evidence.
- REL-02 complete: backend ruff, format, bandit, pip-audit, and full pytest coverage gates passed.
- REL-03 complete: frontend i18n, changed-namespace, lint, typecheck, and coverage gates passed.
- REL-04 complete: OpenAPI and SDK generated artifacts were updated for the current API.
- REL-05 complete: compose stack health passed after the frontend healthcheck fix.
- REL-06 complete: root Playwright smoke passed across core, builder, and fixture flows.
- REL-07 complete: Playwright MCP browser sanity passed with clean current-page console.
- REL-08 complete: known temporary UAT/smoke datasets were cleaned from the authenticated local catalog.
- REL-09 complete: v1007 closeout artifacts record gates, fixes, and caveats.

## Files Touched

- `backend/openapi.json`
- `sdks/python/geolens/api/tiles/cluster_tile_endpoint_tiles_clusters_table_path_z_x_y_pbf_get.py`
- `sdks/python/geolens/models/shared_layer_response.py`
- `sdks/typescript/src/client/index.ts`
- `sdks/typescript/src/client/sdk.gen.ts`
- `sdks/typescript/src/client/types.gen.ts`
- `docker-compose.yml`
- `e2e/collections.spec.ts`
- `.planning/phases/1032-release-hygiene-closeout/1032-01-PLAN.md`
- `.planning/phases/1032-release-hygiene-closeout/1032-01-SUMMARY.md`
- `.planning/phases/1032-release-hygiene-closeout/1032-VERIFICATION.md`
- `.planning/milestones/v1007-ROADMAP.md`
- `.planning/milestones/v1007-REQUIREMENTS.md`
- `.planning/milestones/v1007-MILESTONE-AUDIT.md`

## Caveats

- `make sdks-check` intentionally failed before commit because it generated SDK drift; after the generated artifacts were committed, it passed.

## Follow-up Resolved 2026-05-12

- GitHub Dependabot alerts #36/#37 were dismissed as inaccurate after verifying `origin/main` resolves `urllib3==2.7.0` and `pip-audit` remains clean.
- `docs/testing-and-ci.md` now documents the local testing and CI command map; `.github/workflows/ci.yml` remains canonical.
