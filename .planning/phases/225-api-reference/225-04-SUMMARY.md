---
phase: 225-api-reference
plan: "04"
subsystem: docs
tags: [mdx, starlight, api-reference, authentication, jwt, api-key, oauth]

requires:
  - phase: 224-brand-shell-search
    provides: Expressive Code conventions, frontmatter patterns, Starlight 0.38.4 config

provides:
  - Hand-authored /guides/api/auth MDX page with three auth sections (JWT, API key, OAuth/OIDC)
  - Corrected X-Api-Key header documentation (not Authorization: Bearer <api_key>)
  - Both API key forms (header + query string) documented
  - Forward-link stubs to /guides/admin/users and /guides/admin/oauth

affects: [225-05-ogc, 225-06-landing, 226-quickstart, 227-admin-guide, 228-links-validator]

tech-stack:
  added: []
  patterns:
    - "Starlight MDX frontmatter: title + description only (no per-page lastUpdated/editLink overrides)"
    - "Expressive Code bash blocks with ``` ```bash ``` fence (not sh)"
    - "Placeholder host https://geolens.example.com/api/... in all curl examples"
    - "No body H1 — Starlight derives rendered H1 from frontmatter title"
    - "No custom Astro component imports — markdown-only MDX for prose pages"

key-files:
  created:
    - getgeolens.com/docs/src/content/docs/guides/api/auth.mdx

key-decisions:
  - "API key header documented as X-Api-Key (correcting CONTEXT.md D-12 error) — verified against backend/app/modules/auth/dependencies.py:25"
  - "Both API key forms documented: X-Api-Key header (preferred) and ?api_key= query string"
  - "Three sections in locked order per D-10: JWT Bearer, API keys, OAuth/OIDC"
  - "Forward-links to /guides/admin/users and /guides/admin/oauth are intentional forward-refs — Plan 08 must register them in validator exclude list"
  - "OIDC client-credentials/PKCE explicitly called out as out-of-scope (GeoLens does not support)"

patterns-established:
  - "Auth prose page pattern: intro → resolution order note → section per method → security callout per section"

requirements-completed: [API-03]

duration: 8min
completed: 2026-04-25
---

# Phase 225 Plan 04: API Authentication Page Summary

**Hand-authored `/guides/api/auth.mdx` documenting JWT Bearer, X-Api-Key header + query forms, and OAuth/OIDC with corrected header name verified against backend source**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-04-25T21:02:00Z
- **Completed:** 2026-04-25T21:10:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created `auth.mdx` with three auth sections in the locked D-10 order
- Corrected CONTEXT.md D-12 error: API key header is `X-Api-Key` not `Authorization: Bearer <api_key>`
- Documented both API key forms: header (preferred) and `?api_key=` query string
- All five curl examples use placeholder host `https://geolens.example.com/api/...`
- `astro check` passes with 0 errors

## Task Commits

1. **Task 1: Create auth.mdx with three corrected auth sections** — `3938c3b` (feat) — sibling repo `getgeolens.com` on branch `gsd/phase-225-api-reference`

## Files Created/Modified

- `getgeolens.com/docs/src/content/docs/guides/api/auth.mdx` — Hand-authored API authentication reference page (118 lines)

## Decisions Made

- Followed plan content exactly as specified; the plan provided the precise MDX body.
- D-12 correction applied: `X-Api-Key` header confirmed at `backend/app/modules/auth/dependencies.py:25` — `request.headers.get("X-Api-Key")` is the source of truth.

## Deviations from Plan

None — plan executed exactly as written.

## Verification Results

All acceptance criteria confirmed:

| Check | Result |
|-------|--------|
| `grep -F 'X-Api-Key' auth.mdx` | PASS (present) |
| `! grep -F 'Authorization: Bearer <api_key>' auth.mdx` | PASS (absent) |
| `grep -F 'https://geolens.example.com'` | PASS (present) |
| `! grep -F 'demo.getgeolens.com'` | PASS (absent) |
| H2 section count | 3 (JWT Bearer Tokens, API Keys, OAuth / OIDC) |
| bash block count | 5 (meets ≥5 requirement) |
| `astro check` | 0 errors, 0 warnings |
| No body H1 | PASS |
| No custom Astro components | PASS |

## Section Order (D-10)

1. `## JWT Bearer Tokens` — POST /api/auth/login/ flow, access_token + refresh_token, Bearer header usage
2. `## API Keys` — X-Api-Key header form + ?api_key= query form, resolution order note, /guides/admin/users forward-link
3. `## OAuth / OIDC` — admin-configured, browser auth-code flow, machine client reuse, /guides/admin/oauth forward-link, PKCE out-of-scope statement

## Forward-Link Note

`/guides/admin/users` and `/guides/admin/oauth` are intentional forward-references to Phase 227 content. Plan 08 (links-validator) must register these paths in the `exclude` allow-list (e.g., `exclude: ['/guides/admin/**']`) to prevent build failures until Phase 227 lands.

## Issues Encountered

None.

## Next Phase Readiness

- `auth.mdx` is the first non-trivial hand-authored MDX in the docs tree — establishes conventions for `ogc.mdx` (Plan 05) and `index.mdx` (Plan 06)
- Expressive Code bash block convention confirmed working with `astro check`
- Plan 05 (ogc.mdx) can proceed immediately

---
*Phase: 225-api-reference*
*Completed: 2026-04-25*
