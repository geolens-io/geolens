---
phase: 1137-sharing-and-embed-polish
fixed_at: 2026-05-27T20:45:00Z
review_path: .planning/phases/1137-sharing-and-embed-polish/1137-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 1137: Code Review Fix Report

**Fixed at:** 2026-05-27T20:45:00Z
**Source review:** `.planning/phases/1137-sharing-and-embed-polish/1137-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 7
- Fixed: 7
- Skipped: 0

## Fixed Issues

### CR-01: IPv6 canonical-form divergence produces invalid CSP directive

**Files modified:** `backend/app/modules/embed_tokens/schemas.py`, `backend/tests/test_embed_tokens_csp_no_wildcard.py`
**Commit:** `63ce7a8a`
**Applied fix:** Replaced `parsed.hostname` (which strips IPv6 brackets) with a `parsed.netloc`-based host extraction in `_normalize_origin`. When `parsed.port` is set, the host is extracted via `parsed.netloc.rsplit(":", 1)[0]` which preserves brackets for IPv6 (`[::1]`). Added `test_normalize_origin_ipv6_brackets` regression test covering port-present, no-port, and default-port-stripped cases. 15/15 backend tests pass.

### CR-02: Frontend `normalizeOrigin` accepts wildcard-subdomain origins

**Files modified:** `frontend/src/lib/builder/url-normalize.ts`, `frontend/src/lib/builder/__tests__/url-normalize.test.ts`
**Commit:** `397c0928`
**Applied fix:** Added `parsed.hostname.includes('*')` guard after the WHATWG URL parse succeeds, catching `https://*.example.com` and `https://sub.*.example.com` patterns that bypass the leading-`*` prefix check. Updated the `@throws` docstring to reflect the expanded contract. Added 2 new test cases; 24/24 tests pass.

### WR-01: Stale-closure rollback in `handleAddOrigin` can discard concurrently-added chips

**Files modified:** `frontend/src/components/builder/SharePanel.tsx`
**Commit:** `57180f06`
**Applied fix:** `handleAddOrigin` rollback replaced `setOrigins(origins)` (stale snapshot) with `setOrigins((current) => current.filter((o) => o !== addedCanonical))`. `handleRemoveOrigin` rollback replaced `setOrigins(previous)` (stale snapshot) with `setOrigins((current) => current.includes(removedOrigin) ? current : [...current, removedOrigin])`. Both now use functional setState operating on current state rather than the render-N closure snapshot.

### WR-02: `configOrigins` reference instability causes sync useEffect to fire continuously

**Files modified:** `frontend/src/components/builder/SharePanel.tsx`
**Commit:** `b745762c`
**Applied fix:** Added `useMemo` import and wrapped `configOrigins` declaration in `ShareDialog` with `useMemo(() => activeEmbedToken?.allowed_origins ?? [], [activeEmbedToken?.allowed_origins])`. The `?? []` fallback no longer creates a new array reference on every render when `allowed_origins` is `null`, preventing the sync `useEffect` in `ShareLinkSettings` from wiping in-flight optimistic chip state.

### WR-03: `domainInput` state and `parseOrigins` function are dead code

**Files modified:** `frontend/src/components/builder/SharePanel.tsx`
**Commit:** `be949793`
**Applied fix:** Removed `parseOrigins` function definition (8 lines), removed `const [domainInput, setDomainInput] = useState('')`, removed `setDomainInput('')` from `handleRevoked`. Replaced the 3 `canUseAdvancedSharing ? parseOrigins(domainInput) : []` call sites in `maybeCreateEmbedToken`, `handleRegenerateShareLink`, and `handleRegenerateEmbedToken` with direct `createEmbedToken.mutateAsync({ mapId })` calls with explanatory comments. Net: -26 lines of dead state.

### IN-01: `EmbedPreviewPane` constructs `src` URL via plain string concatenation

**Files modified:** `frontend/src/components/builder/SharePanel.tsx`
**Commit:** `fc6a5bb7`
**Applied fix:** Replaced `const src = \`${origin}/m/${shareToken}?embed=true&et=${embedTokenRaw}\`` with an IIFE using `URLSearchParams({ embed: 'true' })` + `params.set('et', embedTokenRaw)` to match the `generateEmbedCode` URL construction pattern. Preview src and copied embed code are now constructed identically, preventing silent divergence if the token format gains percent-encodable characters.

### IN-02: `showBranding` flashes badge for enterprise users while `useBranding` loads

**Files modified:** `frontend/src/components/viewer/ViewerMap.tsx`, `frontend/src/pages/PublicViewerPage.tsx`
**Commit:** `06fd85d1`
**Applied fix:** Added `branding !== undefined &&` guard in both locations before the `show_badge` check. In `ViewerMap.tsx` the guard is part of the multi-line `showBranding` expression; in `PublicViewerPage.tsx` the single-line `showFooterBranding` now reads `branding !== undefined && (!isEnterprise || branding?.show_badge !== false)`. Enterprise users with `show_badge: false` no longer see a flash on initial mount while the branding query is pending.

---

_Fixed: 2026-05-27T20:45:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
