---
phase: 260325-qrg
verified: 2026-03-25T00:00:00Z
status: gaps_found
score: 4/5 must-haves verified
gaps:
  - truth: "Admin page title uses i18n (UX-3)"
    status: failed
    reason: "useDocumentTitle still called with hardcoded 'Admin Published Maps' string instead of t('sharedMaps.title')"
    artifacts:
      - path: "frontend/src/pages/admin/AdminSharedMapsPage.tsx"
        issue: "Line 223: useDocumentTitle('Admin Published Maps') — should be useDocumentTitle(t('sharedMaps.title'))"
    missing:
      - "Change line 223 in AdminSharedMapsPage.tsx from useDocumentTitle('Admin Published Maps') to useDocumentTitle(t('sharedMaps.title'))"
---

# Phase 260325-qrg: Map Sharing / Embed Controls Verification Report

**Phase Goal:** Fix wiring bugs (cascade revoke, cache invalidation, expired link warning), type drift, and UX issues in admin shared maps page and map creator ShareDialog.
**Verified:** 2026-03-25
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Admin bulk-revoking embed tokens immediately updates the embed count shown on parent share token rows | VERIFIED | `useBulkRevokeEmbedTokens.onSuccess` invalidates both `['admin', 'embed-tokens']` and `['admin', 'share-tokens']` at `use-admin.ts:217-218` |
| 2 | Admin revoking a share token also deactivates all embed tokens for that map | VERIFIED | `admin_revoke_share_token` at `admin/router.py:663-671` queries active embed IDs by `map_id` and calls `bulk_revoke_embed_tokens`; cascade test at `test_maps.py:910-952` validates behavior |
| 3 | Map creator ShareDialog shows a warning when the share link has expired | VERIFIED | `isExpired` bool derived at `SharePanel.tsx:91`; AlertTriangle + destructive text rendered at lines 331-340; `t('share.expired')` key present in all 4 locales |
| 4 | Frontend EmbedTokenResponse type includes all backend-returned fields | VERIFIED | `types/api.ts:991-992` — `name?: string \| null` and `scoped_dataset_ids?: string[]` present |
| 5 | Admin page document title uses i18n (UX-3) | FAILED | `AdminSharedMapsPage.tsx:223` still calls `useDocumentTitle('Admin Published Maps')` — hardcoded English string not replaced with `t('sharedMaps.title')` |

**Score:** 4/5 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/admin/router.py` | Cascade revoke of embed tokens when admin revokes share token | VERIFIED | Lines 651-671: imports `EmbedToken`, `bulk_revoke_embed_tokens`; queries active embeds by `map_id`; calls bulk revoke before commit |
| `frontend/src/hooks/use-admin.ts` | Cache invalidation for share-tokens after embed bulk-revoke | VERIFIED | Lines 217-218: both `['admin', 'embed-tokens']` and `['admin', 'share-tokens']` invalidated in `onSuccess` |
| `frontend/src/components/builder/SharePanel.tsx` | Expired share link warning in ShareDialog | VERIFIED | `isExpired` at line 91; AlertTriangle + `t('share.expired')` rendered at lines 331-336; expiry text uses `text-destructive` class when expired |
| `frontend/src/types/api.ts` | Complete EmbedTokenResponse type matching backend schema | VERIFIED | `EmbedTokenResponse` at lines 988-1000 includes `name?: string \| null` and `scoped_dataset_ids?: string[]` |
| `backend/tests/test_maps.py` | Test for cascade revoke behavior | VERIFIED | `test_admin_revoke_share_token_cascades_embed_tokens` at line 910 inside `TestAdminShareTokenListing`; creates map, share token, embed token, revokes share, asserts embed `is_active=False` |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `backend/app/admin/router.py` | `backend/app/embed_tokens/service.py` | cascade revoke call in `admin_revoke_share_token` | WIRED | `bulk_revoke_embed_tokens` imported and called at line 671 with embed IDs queried for `token_obj.map_id` |
| `frontend/src/hooks/use-admin.ts` | TanStack Query cache | `invalidateQueries` in `useBulkRevokeEmbedTokens.onSuccess` | WIRED | Both `['admin', 'embed-tokens']` and `['admin', 'share-tokens']` invalidated at lines 217-218 |

---

### Data-Flow Trace (Level 4)

Not applicable — this phase targets wiring fixes in service/hook layer, not new UI components with dynamic data sources. All affected components (SharePanel, AdminSharedMapsPage) use existing data queries already verified.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| TypeScript compiles cleanly | `npx tsc --noEmit` (from `frontend/`) | No errors | PASS |
| Cascade test exists and is substantive | `grep -n "cascade" test_maps.py` | Found at line 910; full test body at lines 910-952 with assertions | PASS |
| `share-tokens` invalidation present | `grep -n "share-tokens" use-admin.ts` | Line 218: `qc.invalidateQueries({ queryKey: ['admin', 'share-tokens'] })` inside `useBulkRevokeEmbedTokens.onSuccess` | PASS |
| `expired` i18n key in all 4 locales | `grep "expired" */builder.json` | Found at line 157 in en, es, fr, de | PASS |
| Admin page title i18n | `grep -n "useDocumentTitle" AdminSharedMapsPage.tsx` | Line 223: hardcoded `'Admin Published Maps'` — NOT using `t('sharedMaps.title')` | FAIL |

---

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|---------|
| QRG-01 | Fix wiring bugs and UX issues in admin shared maps / ShareDialog | PARTIAL | 4 of 5 items fixed; UX-3 (document title i18n) not applied |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `frontend/src/pages/admin/AdminSharedMapsPage.tsx` | 223 | Hardcoded English string `'Admin Published Maps'` in `useDocumentTitle` | Warning | Document title shown in browser tab will not change with locale; `t('sharedMaps.title')` already exists in `admin.json` with value `"Published Maps"` and `t` is in scope at that line |

Note: `placeholderData: keepPreviousData` entries in `use-admin.ts` are TanStack Query API parameters, not stub indicators.

---

### Human Verification Required

#### 1. Cascade Revoke — Live Behavior

**Test:** In admin UI at `/admin/shared-maps`, expand a share token row that has active embed tokens, then click revoke on the share token.
**Expected:** Share token is revoked AND all child embed tokens are simultaneously deactivated — not just hidden but actually `is_active=False` in DB.
**Why human:** Cannot verify DB side-effects of the admin revoke endpoint without running the full stack.

#### 2. Expired Share Link Warning — Visual

**Test:** In map builder, open ShareDialog for a map whose share token has an `expires_at` date in the past.
**Expected:** An AlertTriangle icon and "This share link has expired" text appear above the expiry date; the date itself renders in red/destructive color.
**Why human:** Requires a token with a past expiry date to be present; `isExpired` logic depends on `new Date()` at runtime.

#### 3. Bulk Revoke Cache Refresh — Real-Time UI

**Test:** In admin shared maps page, expand a share token row, select all embed tokens, click "Bulk Revoke". Without a page refresh, observe the parent row's embed count column.
**Expected:** Embed count updates immediately to reflect the revoked tokens.
**Why human:** TanStack Query cache invalidation effect requires a live running frontend.

---

### Gaps Summary

One gap remains from the UX-3 task: `AdminSharedMapsPage.tsx` line 223 calls `useDocumentTitle('Admin Published Maps')` with a hardcoded English string. The plan required this to use `t('sharedMaps.title')`. The translation key exists in `admin.json` (value: `"Published Maps"`) and `t` is already in scope at that line — making this a one-line fix. This is a minor UX regression rather than a functional bug, but it was an explicit requirement in the plan.

All three functional bugs (BUG-1 cache invalidation, BUG-2 cascade revoke, BUG-3 expired warning) are correctly implemented and wired. The DRIFT-1 type fix is complete. Only UX-3 was missed.

---

_Verified: 2026-03-25_
_Verifier: Claude (gsd-verifier)_
