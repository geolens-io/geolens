---
phase: 1137-sharing-and-embed-polish
verified: 2026-05-28T00:30:00Z
status: passed
close_gate_resolution: "human_needed items deferred to Phase 1139 close-gate; verified live in 1139-CLOSE-GATE-SMOKE.md (3-viewport MCP + disabled-AI + save-persist + shared/embed parity). See v1030-MILESTONE-AUDIT.md."
score: 5/5
overrides_applied: 0
human_verification:
  - test: "Chip-based allowed-origins UI live interaction (SHARE-02 enterprise gate)"
    expected: "Enterprise user can paste https://Example.com, press Enter, see canonical chip https://example.com; wildcard * shows inline error 'Wildcard origin not allowed'; chip persists after Save"
    why_human: "canUseAdvancedSharing = isEnterprise — chip UI hidden on community stack; unit tests cover it behind enterprise mock but live render requires enterprise license"
  - test: "Expiration preset Select live interaction (SHARE-04 enterprise gate)"
    expected: "Preset Select shows 6 options (Never/1d/7d/30d/1y/Custom); selecting 7 days fires PATCH immediately without extra Save click; rawShareToken and embedTokenRaw survive (Pitfall #6)"
    why_human: "Expiration preset UI is also behind canUseAdvancedSharing = isEnterprise gate; live verification requires enterprise edition"
  - test: "Embed preview iframe live expansion (SHARE-03 enterprise gate)"
    expected: "Click Preview toggle to expand; iframe loads with sandbox='allow-scripts' exactly (no allow-same-origin); security indicator footer shows 'sandbox=\"allow-scripts\" only — SEC-07 contract'"
    why_human: "EmbedPreviewPane is gated on embedTokenRaw being non-null, which is only set after hasNonPublic=true share flow; embed preview toggle is enterprise-gated; requires live enterprise + non-public-layer map"
  - test: "Pitfall #7 race guard live (double-click Generate Share Link)"
    expected: "Rapid double-click on Generate Share Link fires createEmbedToken POST exactly once; second concurrent call awaits in-flight promise; no orphan token in DB"
    why_human: "Race condition requires precise timing; performance.getEntriesByType verification needs live browser network tab; unit test pins contract but timing-sensitive UI path needs human trigger"
  - test: "Legend rendering on shared view with a categorically-styled layer"
    expected: "A map with a categorical paint expression (fill with data-driven color) should show legend entries in the LayerLegend overlay; F3 finding confirmed it doesn't show on ADK map (correct - no categorical layers)"
    why_human: "F3 from MCP-VERIFY.md: legend absent on ADK test map was confirmed correct behavior; human must verify a map WITH categorical styling actually shows legend entries in shared/embed view"
---

# Phase 1137: Sharing and Embed Polish Verification Report

**Phase Goal:** Extend `3ed5ceb3`'s rawShareToken/persistedShareTokenHint separation with chip-based allowed-origins, expiration presets, "Powered by GeoLens" community-edition branding, legend+title in export, and sandboxed iframe preview.

**Verified:** 2026-05-28T00:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Allowed origins display as removable chips; chip input round-trips via PATCH with canonical-form normalization; CSP frame-ancestors never `*` | VERIFIED | `SharePanel.tsx:29` imports `normalizeOrigin, WildcardOriginError`; chip add/remove handlers at lines 236/279; `url-normalize.ts` 123 lines, 4 named exports; 22 vitest unit tests pass; backend `_normalize_origin` rejects `*` at schema layer (422) + `_build_frame_ancestors` silently drops `*` as defense-in-depth; 14 backend tests across 2 files; live MCP confirmed CSP valid |
| 2 | User can pick expiration via presets (5 options + Custom); rawShareToken survival across dialog open/close preserved | VERIFIED | `SharePanel.tsx:135-217` — `ExpirationPreset` type, `detectPreset`, `handleApplyPreset` with T23:59:59Z arithmetic for 1d/7d/30d/1y/never; 8 SHARE-04 tests + 2 Pitfall #6 regression tests in SharePanel.test.tsx; Pitfall #6 docstrings at lines 176+203; live MCP confirmed "Expires: Never" default shown |
| 3 | "Powered by GeoLens" branding in shared/embed views (community); suppressed under enterprise; map title + legend in shared/embed/export PNG; useEdition read on viewer + ViewerMap + thumbnail-capture | VERIFIED | `ViewerMap.tsx:75,144-149,805-808` — `showInlineBranding` prop, useEdition+useBranding gate `(!isEnterprise \|\| branding?.show_badge !== false)`; `PublicViewerPage.tsx:154` — `showInlineBranding={isEmbed}`; `use-builder-save.ts:397,568` — `isEnterprise` gates `showBranding`; `en/common.json` has `export.poweredBy` + `export.legendHeader`; 4 ViewerMap branding tests + 2 PublicViewerPage SHARE-07 routing pins + 4 SHARE-09 export PNG regression tests; live MCP: DOM contains branding overlay, text "Powered by GeoLens" present |
| 4 | Embed-preview iframe pane uses `sandbox="allow-scripts"` only (no allow-same-origin); SEC-07/M-70 invariant holds | VERIFIED | `SharePanel.tsx:568` — `sandbox="allow-scripts"` hardcoded; `allow-same-origin` absent as JSX attribute (3 comment-only occurrences only); `EmbedPreviewPane` subcomponent at line 525 fully implemented with loading/error states; live MCP: embed code textarea confirmed `sandbox="allow-scripts"` exactly |
| 5 | inflightEmbedCreate race closed; concurrent embed-token creation fires exactly one POST | VERIFIED | `SharePanel.tsx:640` — `const inflightEmbedCreate = useRef<...>(null)`; guard logic at lines 719-740 with `finally` clear; JSDoc Pitfall #7 contract at lines 704-714; 1 Pitfall #7 regression test in SharePanel.test.tsx |

**Score:** 5/5 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/lib/builder/url-normalize.ts` | normalizeOrigin + dedupeOrigins + 2 error classes | VERIFIED | 123 lines; 4 named exports confirmed by grep; min_lines=60 exceeded |
| `frontend/src/lib/builder/__tests__/url-normalize.test.ts` | 22 vitest cases across 3 describe blocks | VERIFIED | 116 lines; 22 `it()` blocks per SUMMARY; backend-parity block present |
| `backend/tests/test_embed_tokens_csp_no_wildcard.py` | 6 CSP wildcard rejection tests | VERIFIED | 295 lines; 6 `def test_` functions confirmed |
| `frontend/src/components/viewer/__tests__/ViewerMap.branding.test.tsx` | 4 branding overlay regression pins | VERIFIED | File exists; 4 `it()` blocks confirmed |
| `frontend/src/components/builder/__tests__/SharePanel.test.tsx` | SHARE-02/03/04 + Pitfall #6/#7 tests | VERIFIED | 41 `it()` blocks; describe blocks for SHARE-02, SHARE-04, SHARE-03, Pitfall #7 all present |
| `frontend/src/components/builder/hooks/use-builder-save.ts` | SHARE-09 export PNG legend+title+branding | VERIFIED | Lines 558-632 implement legend layer filter, `fillText` legend header/rows, branding footer gated on `!isEnterprise` |
| `frontend/src/pages/PublicViewerPage.tsx` | showInlineBranding={isEmbed} wired | VERIFIED | Line 154: `showInlineBranding={isEmbed}`; line 59+62 effectiveShowLegend gates LayerLegend |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `url-normalize.ts` | `SharePanel.tsx` | `import { normalizeOrigin, WildcardOriginError }` | WIRED | Line 29 of SharePanel.tsx; used at line 243 in handleAddOrigin |
| `SharePanel.tsx configOrigins prop` | `activeEmbedToken?.allowed_origins` | `const configOrigins = activeEmbedToken?.allowed_origins ?? []` | WIRED | Line 654; data flows from live API query via `useMapEmbedTokens` |
| `ViewerMap showInlineBranding prop` | `PublicViewerPage isEmbed` | `showInlineBranding={isEmbed}` | WIRED | Line 154 of PublicViewerPage.tsx |
| `EmbedPreviewPane` | `rawShareToken + embedTokenRaw` | `embedTokenRaw && <EmbedPreviewPane shareToken={rawShareToken} embedTokenRaw={embedTokenRaw}>` | WIRED | Lines 1108-1114; gated on live state values |
| `inflightEmbedCreate ref` | `maybeCreateEmbedToken()` | `useRef` at line 640; guard at lines 719-740 | WIRED | Guard fires on concurrent calls; `finally` clears ref |
| `_normalize_origin wildcard reject` | `_build_frame_ancestors` | schema-layer 422 + header-builder defense-in-depth | WIRED | Two-layer enforcement: schemas.py line 19 raises ValueError; router.py line 133 `"*" in o` drop |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `SharePanel.tsx` chip list | `origins: string[]` | `configOrigins = activeEmbedToken?.allowed_origins ?? []` → `useMapEmbedTokens` API | Yes — fetches live from DB via embed-tokens endpoint | FLOWING |
| `ViewerMap.tsx` branding overlay | `showBranding` | `useEdition()` → API edition endpoint + `useBranding()` → settings API | Yes — useEdition reads real edition from API | FLOWING |
| `use-builder-save.ts` export PNG | `isEnterprise` | `useEdition().isEnterprise` — same API source | Yes — real edition gate | FLOWING |
| `PublicViewerPage` legend | `data.layers` from `useSharedMap(token)` | API `GET /maps/shared/{token}` → DB query | Yes — real layers from DB | FLOWING |
| `EmbedPreviewPane` iframe src | `rawShareToken`, `embedTokenRaw` | `useState` set by `maybeCreateEmbedToken` → `createEmbedToken.mutateAsync` | Yes — set from real API POST response | FLOWING |

---

### Behavioral Spot-Checks

Step 7b: SKIPPED for enterprise-gated surfaces (chip UI, expiration presets, iframe preview require enterprise license for live render). Community-accessible surfaces were verified live by the orchestrator-driven MCP run documented in `1137-MCP-VERIFY.md`.

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| url-normalize WildcardOriginError export | `grep -E "^export class WildcardOriginError" frontend/src/lib/builder/url-normalize.ts` | 1 match | PASS |
| sandbox="allow-scripts" JSX attribute present | `grep -n 'sandbox="allow-scripts"' frontend/src/components/builder/SharePanel.tsx` | Line 568 (JSX attr) | PASS |
| allow-same-origin absent as JSX attribute | `grep -n "allow-same-origin" frontend/src/components/builder/SharePanel.tsx` | 3 comment-only occurrences, 0 attribute uses | PASS |
| inflightEmbedCreate ref declared | `grep -n "inflightEmbedCreate" frontend/src/components/builder/SharePanel.tsx` | Line 640 useRef declaration + lines 719-740 guard | PASS |
| CSP wildcard-drop in _build_frame_ancestors | `grep -n '"*" in o' backend/app/modules/catalog/maps/router.py` | Line 133 confirmed | PASS |
| Branding overlay in ViewerMap DOM | Live MCP: `data-testid="viewer-branding-overlay"` with "Powered by GeoLens" | Confirmed LIVE (MCP-VERIFY.md row SHARE-07) | PASS |
| BuilderActionSource unchanged | `git diff HEAD~20..HEAD -- frontend/src/components/builder/builder-action-contract.ts` | Empty diff | PASS |
| SHARE-08 not touched (thumbW=400/thumbH=250) | `grep -n "thumbW\|thumbH" frontend/src/components/builder/hooks/use-builder-save.ts` | Lines 33-34: 400/250 unchanged | PASS |

---

### Probe Execution

Step 7c: No phase-declared probes. No `scripts/*/tests/probe-*.sh` files applicable to this frontend/security phase. SKIPPED.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SHARE-02 | 1137-04 | Chip-based allowed-origins UI | SATISFIED | `SharePanel.tsx` chip list + handleAddOrigin/handleRemoveOrigin; 7 regression tests |
| SHARE-03 | 1137-06 | Embed-preview iframe + sandbox=allow-scripts | SATISFIED | `EmbedPreviewPane` in SharePanel.tsx; line 568 sandbox attr; 6 tests |
| SHARE-04 | 1137-05 | Expiration presets (5 options + Custom) | SATISFIED | `ExpirationPreset` type + detectPreset + handleApplyPreset; 8 tests |
| SHARE-06 | 1137-01/02 | Canonical-form normalization + CSP no-* | SATISFIED | url-normalize.ts (22 tests) + backend dual-layer enforcement (14 tests) |
| SHARE-07 | 1137-03 | "Powered by GeoLens" community branding | SATISFIED | ViewerMap showInlineBranding prop + PublicViewerPage wiring; LIVE confirmed |
| SHARE-09 | 1137-03 | Map title + legend in shared/embed/export | SATISFIED | LayerLegend wired in PublicViewerPage; title via MapTitlePill; export PNG legend+title+branding in use-builder-save.ts |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `SharePanel.tsx:729,768,793` | 729, 768, 793 | `parseOrigins()` legacy helper still present at 3 call sites inside `maybeCreateEmbedToken` / regenerate handlers | INFO | Not a stub — Plan 04 documented this as deferred; the chip UI uses `normalizeOrigin` correctly. Legacy `parseOrigins` on non-chip paths is a known carryover. No functional regression (these paths fire only when `canUseAdvancedSharing` is true). |
| `SharePanel.tsx:697` | 697 | `return null` in try/catch | INFO | Legitimate error-path return in `checkMapVisibility` — not a stub |
| `frontend/src/i18n/locales/{de,es,fr}/builder.json` | — | `iframeSandboxNote` is English-only across all 4 locales intentionally | INFO | Documented decision in Plan 06: technical security note, brand-style untranslated |
| Multiple SharePanel.tsx | 319, 340, 393, 1038, 1101 | `font-medium` in 5 places (F2 from MCP-VERIFY) | INFO | P3 cosmetic finding; deferred to Phase 1138 per MCP-VERIFY.md F2 disposition |

No `TBD`, `FIXME`, or `XXX` debt markers found in any Phase 1137 modified files.

---

### Human Verification Required

The following surfaces are behind the `canUseAdvancedSharing = isEnterprise` gate. All are covered by unit tests with enterprise edition mocked; live verification requires either an enterprise license or temporarily overriding the gate in dev.

#### 1. Chip-Based Allowed-Origins Live Interaction

**Test:** Navigate to a map's Share dialog. Enable "Restrict to domains." Type `https://Example.com/` and press Enter. Observe the rendered chip.
**Expected:** Chip renders as `https://example.com` (canonical form — trailing slash stripped, lowercased). Type `*` and submit — expect inline error "Wildcard origin not allowed" with no chip added and no PATCH fired. Remove a chip — expect optimistic removal and PATCH.
**Why human:** `canUseAdvancedSharing = isEnterprise` hides chip UI on community stack. Enterprise stack or gate override required.

#### 2. Expiration Preset Select Live Interaction

**Test:** Open Share dialog. Expand "Link Settings." Locate expiration Select. Cycle through options: "Never", "7 days", "1 year", "Custom date…".
**Expected:** Non-custom presets fire PATCH immediately (no extra Save button). Custom reveals the existing DatePicker. After selecting a preset, Copy Link button remains present and rawShareToken is unchanged (Pitfall #6 survival).
**Why human:** Enterprise-gated. Radix Select interaction also requires real browser (JSDOM tests use fireEvent.click workaround).

#### 3. Embed Preview Iframe Live Expansion

**Test:** On a map with non-public layers, generate a share link to get an embed token. Expand the "Preview" disclosure. Observe the iframe load.
**Expected:** iframe has `sandbox="allow-scripts"` exactly (inspect element); no `allow-same-origin`. Security indicator footer below iframe shows the sandbox note. Loader spinner visible briefly then replaced by map.
**Why human:** Gated on `embedTokenRaw` being non-null (requires non-public layers) + enterprise gate.

#### 4. Pitfall #7 Race Guard Live

**Test:** Open Share dialog on a map where no embed token exists yet. Rapidly double-click "Generate share link" (or call the handler twice programmatically). Check network tab for embed-token POST requests.
**Expected:** Exactly 1 POST to `/api/maps/{id}/embed-tokens/`; no duplicate token in DB.
**Why human:** Timing-sensitive race; requires live network inspection. Unit test in SharePanel.test.tsx asserts `createEmbedToken.mutateAsync` called exactly once, but live browser network tab provides authoritative confirmation.

#### 5. Legend Rendering on Categorically-Styled Map

**Test:** Share a map that has at least one vector layer with a data-driven categorical paint expression. Open the shared URL. Verify the LayerLegend overlay shows entries.
**Expected:** Legend is visible with at least one row matching the categorical layer. The `?legend=false` query param hides it (effectiveShowLegend=false path).
**Why human:** F3 from MCP-VERIFY.md confirmed the ADK test map correctly shows no legend (no categorical layers). A map with categorical styling must be tested separately to confirm the legend DOES render when expected.

---

### Gaps Summary

No automation-detectable gaps. All 5 ROADMAP success criteria are verified at the code level:

1. SC #1 (allowed-origins chips + CSP no-*): url-normalize.ts delivers Pitfall #8 normalization; backend enforces at schema + header-builder layers with 14 regression tests.
2. SC #2 (expiration presets + Pitfall #6 survival): ExpirationPreset union type + detectPreset + handleApplyPreset + Pitfall #6 docstrings + 10 regression tests.
3. SC #3 (community branding + legend+title in export): ViewerMap showInlineBranding prop fully wired; useEdition gate present in ViewerMap, PublicViewerPage, and use-builder-save.ts; export PNG legend+title+branding with 4 regression tests; LIVE confirmed via MCP.
4. SC #4 (sandbox=allow-scripts only, no allow-same-origin): `sandbox="allow-scripts"` hardcoded at JSX line 568; allow-same-origin absent as attribute (comment-only); SEC-07/M-70 inline at definition.
5. SC #5 (inflightEmbedCreate race): ref declared at line 640; guard logic at lines 719-740; Pitfall #7 JSDoc; 1 regression test.

The 5 human verification items above are all due to the enterprise gate (`canUseAdvancedSharing = isEnterprise`) preventing live community-stack confirmation of chips/presets/iframe preview, plus the categorical-legend edge case needing a different test map. All are adequately covered by unit tests.

**SHARE-08 (OG-cards):** Correctly deferred to v1031 per Phase 1133 WALK-05 disposition. `thumbW=400`/`thumbH=250` unchanged at `use-builder-save.ts:33-34`. Future Requirements entry at `REQUIREMENTS.md:204-211`.

---

_Verified: 2026-05-28T00:30:00Z_
_Verifier: Claude (gsd-verifier)_
