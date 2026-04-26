---
phase: 225-api-reference
plan: "10"
subsystem: docs-site
tags: [verify-build, llms-txt, ci, assertions, pagefind, openapi]
dependency_graph:
  requires: [225-02, 225-03, 225-04, 225-05, 225-06, 225-09]
  provides: [CI gate for Phase 225 entire surface]
  affects: [getgeolens.com/docs/scripts/verify-build.sh, getgeolens.com/docs/public/llms.txt]
tech_stack:
  added: []
  patterns: [bash assertions with FAIL/exit 1 idiom, nullglob shopt guards, node -e inline JSON validation]
key_files:
  created: []
  modified:
    - getgeolens.com/docs/scripts/verify-build.sh
    - getgeolens.com/docs/public/llms.txt
decisions:
  - "Used shopt nullglob around the auto-generated-page loop so an empty dist/guides/api/operations/tags/ directory fails the prior ls assertion rather than silently passing the loop"
  - "Negative grep in API-03 checks both HTML-encoded form (Authorization: Bearer &lt;api_key&gt;) and raw form — covers both Astro's rendering paths"
  - "Did not grep dist/pagefind/ binary indexes per RESEARCH.md Pitfall 3; used data-pagefind-body presence/absence on rendered HTML instead"
metrics:
  duration: "~8 minutes"
  completed: "2026-04-25"
  tasks_completed: 2
  files_modified: 2
---

# Phase 225 Plan 10: Build Verification & llms.txt Summary

Closed the Phase 225 verification loop by appending nine assertions to `verify-build.sh` (covering API-01 through API-05, CI-01, D-21/D-24, and SEO-04 extension) and extending `llms.txt` with two new guide entries.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Extend llms.txt with /guides/api/auth and /guides/api/ogc | 13a4e25 | docs/public/llms.txt |
| 2 | Append Phase 225 assertion fence to verify-build.sh | a5b1425 | docs/scripts/verify-build.sh |

## verify-build.sh Final State

- **Line count:** 226 lines (was 143, +83)
- **Total `Asserting` echoes:** 29 (was 20, +9 new Phase 225 assertions)

New Phase 225 assertions appended (paste of grep output):
```
echo "Asserting API-01: openapi snapshot present and non-empty in src/content/openapi/..."
echo "Asserting API-02: starlight-openapi rendered tag overview pages exist in dist/guides/api/operations/tags/..."
echo "Asserting D-21 / D-24: auto-generated reference pages are EXCLUDED from Pagefind (no data-pagefind-body)..."
echo "Asserting D-21 / D-24: hand-authored /guides/api/ pages REMAIN indexed (data-pagefind-body present)..."
echo "Asserting SEO-04 extension: llms.txt now includes /guides/api/auth and /guides/api/ogc..."
echo "Asserting API-03: auth.mdx uses X-Api-Key (NOT Authorization: Bearer <api_key>)..."
echo "Asserting API-04: ogc.mdx contains OAPIF, pystac-client, and CQL2 examples..."
echo "Asserting API-05: src/content/openapi/README.md exists and references fetch-openapi..."
echo "Asserting CI-01: starlight-links-validator pinned in package.json..."
```

Final line of file: `echo "All build-artifact assertions passed."` (preserved)

## llms.txt Final State

- **Bullet count under `## Guides`:** 6 (was 4, +2)
- New URLs added:
  - `https://docs.getgeolens.com/guides/api/auth`
  - `https://docs.getgeolens.com/guides/api/ogc`

## Integration Build + Verify Result

```
$ cd /Users/ishiland/Code/getgeolens.com/docs && rm -rf dist && npm run build && bash scripts/verify-build.sh
...
08:22:35 [build] 237 page(s) built in 3.86s
08:22:35 [build] Complete!
...
Asserting API-01: openapi snapshot present and non-empty in src/content/openapi/...
Asserting API-02: starlight-openapi rendered tag overview pages exist in dist/guides/api/operations/tags/...
Asserting D-21 / D-24: auto-generated reference pages are EXCLUDED from Pagefind (no data-pagefind-body)...
Asserting D-21 / D-24: hand-authored /guides/api/ pages REMAIN indexed (data-pagefind-body present)...
Asserting SEO-04 extension: llms.txt now includes /guides/api/auth and /guides/api/ogc...
Asserting API-03: auth.mdx uses X-Api-Key (NOT Authorization: Bearer <api_key>)...
Asserting API-04: ogc.mdx contains OAPIF, pystac-client, and CQL2 examples...
Asserting API-05: src/content/openapi/README.md exists and references fetch-openapi...
Asserting CI-01: starlight-links-validator pinned in package.json...
All build-artifact assertions passed.
```

Exit code: 0

## Deviations from Plan

None — plan executed exactly as written. The Phase 225 fence with 9 assertion blocks was inserted verbatim from the plan spec, preserving all Phase 223 and 224 assertions.

## Self-Check: PASSED

- verify-build.sh exists: FOUND
- llms.txt contains /guides/api/auth: FOUND
- llms.txt contains /guides/api/ogc: FOUND
- Commit 13a4e25 (llms.txt): FOUND
- Commit a5b1425 (verify-build.sh): FOUND
- `bash scripts/verify-build.sh` after fresh build: exits 0 with "All build-artifact assertions passed."
