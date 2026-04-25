---
phase: 224
plan: "03"
subsystem: docs-site
tags: [seo, search, shell, nav, docs]
dependency_graph:
  requires: []
  provides: [ec-pagefind-weight-plugin, llms-txt-stub, guide-placeholder-pages, marketing-docs-link]
  affects: [224-04-astro-config-wiring, 223-02-verify-build-sh]
tech_stack:
  added: []
  patterns: [expressive-code-plugin, astro-mdx-content, static-public-file]
key_files:
  created:
    - getgeolens.com/docs/public/llms.txt
    - getgeolens.com/docs/plugins/ec-pagefind-weight.mjs
    - getgeolens.com/docs/src/content/docs/guides/quickstart/index.mdx
    - getgeolens.com/docs/src/content/docs/guides/user/index.mdx
    - getgeolens.com/docs/src/content/docs/guides/admin/index.mdx
    - getgeolens.com/docs/src/content/docs/guides/api/index.mdx
  modified:
    - getgeolens.com/src/components/layout/Nav.astro
decisions:
  - "EC plugin (postprocessRenderedBlock) over rehype plugin for data-pagefind-weight — rehype is discarded by EC's render pipeline (Pivot #1)"
  - "rel=noopener only on Docs nav link — preserves Referer header for Phase 228 cross-site analytics signal"
  - "Placeholder index.mdx files carry NO pagefind: false — must remain search-indexable"
metrics:
  duration: "~5 minutes"
  completed: "2026-04-25"
  tasks_completed: 2
  files_changed: 7
---

# Phase 224 Plan 03: Static Assets, EC Plugin, Placeholder Content, and Marketing Nav Summary

Authored 7 files that Plan 04 (astro.config wiring) will reference: the SEO-04 llms.txt stub, the SEARCH-02 Expressive Code plugin for code-block weight de-ranking, four placeholder guide index pages for Starlight sidebar autogenerate, and the marketing Nav.astro Docs cross-site link.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Author llms.txt + EC plugin + 4 placeholder index.mdx files | bbf718c | docs/public/llms.txt, docs/plugins/ec-pagefind-weight.mjs, 4x guides/*/index.mdx |
| 2 | Patch marketing Nav.astro — add "Docs" link after Quickstart | 104b5b3 | src/components/layout/Nav.astro |

## Success Criteria

- [x] SEO-04: docs/public/llms.txt exists with all 4 canonical guide URLs
- [x] SEARCH-02: docs/plugins/ec-pagefind-weight.mjs exports pluginPagefindWeight using definePlugin + postprocessRenderedBlock
- [x] SHELL-01 (placeholder content): 4 index.mdx files exist with locked "(coming soon)" titles
- [x] SHELL-05 (marketing side): Nav.astro has a Docs link with `href="https://docs.getgeolens.com"`, `rel="noopener"` (no noreferrer), no target="_blank", positioned AFTER Quickstart

## Deviations from Plan

None — plan executed exactly as written.

One automated verification command produced two false-positive failures that do not represent actual defects:

1. `grep -qE '>\s*Docs\s*<'` — failed because "Docs" is on its own indented line (between `>` and `</a>` on separate lines), which is correct multi-line Astro markup. The plan's own markup spec shows this indented pattern.

2. `! grep -qF 'rel="noopener noreferrer"'` — failed because the pre-existing GitHub icon anchor already carried `rel="noopener noreferrer"` before this plan. The Docs anchor correctly uses `rel="noopener"` only.

Both done-criteria items were verified manually and pass.

## Known Stubs

- `getgeolens.com/docs/src/content/docs/guides/quickstart/index.mdx` — intentional placeholder; content ships in Phase 226
- `getgeolens.com/docs/src/content/docs/guides/user/index.mdx` — intentional placeholder; content ships in Phase 227
- `getgeolens.com/docs/src/content/docs/guides/admin/index.mdx` — intentional placeholder; content ships in Phase 227
- `getgeolens.com/docs/src/content/docs/guides/api/index.mdx` — intentional placeholder; content ships in Phase 225

These stubs are by design (D-35) — placeholders must exist so Starlight autogenerate has content to render and the sidebar groups resolve to real URLs. They are search-indexable (no `pagefind: false`).

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced.

## Self-Check: PASSED

- [x] getgeolens.com/docs/public/llms.txt — FOUND
- [x] getgeolens.com/docs/plugins/ec-pagefind-weight.mjs — FOUND
- [x] getgeolens.com/docs/src/content/docs/guides/quickstart/index.mdx — FOUND
- [x] getgeolens.com/docs/src/content/docs/guides/user/index.mdx — FOUND
- [x] getgeolens.com/docs/src/content/docs/guides/admin/index.mdx — FOUND
- [x] getgeolens.com/docs/src/content/docs/guides/api/index.mdx — FOUND
- [x] Nav.astro Docs link — FOUND (line 90)
- [x] Commit bbf718c — FOUND
- [x] Commit 104b5b3 — FOUND
