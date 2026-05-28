# Phase 1137 — Live MCP Smoke Checklist (orchestrator-driven)

> **OPERATOR NOTE:** This is NOT an executor task. The orchestrator calls `mcp__playwright__*`
> tools directly per item below. Do NOT spawn gsd-executor for live browser steps — that
> violates the `feedback_playwright_mcp_orchestrator_only` memory. Executors do not have
> `mcp__playwright__*` tools and cannot run this smoke.

---

## Pre-Flight

Before beginning, confirm the following via `Bash`:

```bash
docker compose ps --format '{{.Name}}\t{{.Status}}' | grep -E 'api|worker|frontend|db|titiler'
```

Expected: 5 rows showing `Up` (or `healthy`) for `api`, `worker`, `frontend`, `db`, `titiler`.
If any container is not running, surface to operator before proceeding.

**Canonical map:** `c39be324-6815-40e5-8143-00a2723827b2` (ADK High Peaks — Terrain & Trails)
**Base URL:** `http://localhost:8080`
**Admin credentials:** `admin` / `admin` (set via `GEOLENS_ADMIN_USERNAME` / `GEOLENS_ADMIN_PASSWORD`)

---

## Section 1: SHARE-02 / SHARE-06 — Chip-Based Allowed Origins

**REQ IDs:** SHARE-02 (chip add/remove optimistic UI), SHARE-06 (canonical form normalization + wildcard rejection)
**Starting URL:** `http://localhost:8080/maps/c39be324-6815-40e5-8143-00a2723827b2`

### Steps

**Step 1.1 — Navigate to builder**
- Tool: `mcp__playwright__browser_navigate`
- URL: `http://localhost:8080/maps/c39be324-6815-40e5-8143-00a2723827b2`
- Wait for map canvas to settle (no spinner in page title).

**Step 1.2 — Sign in (if not already authenticated)**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.cookie.includes('session') || document.querySelector('[data-testid="auth-form"]') !== null`
- If the login form is visible, use `mcp__playwright__browser_type` on the username input, then the password input, then `mcp__playwright__browser_click` on the Sign In button.

**Step 1.3 — Open Share dialog**
- Tool: `mcp__playwright__browser_click`
- Selector: `button[aria-label="Share"], button:has-text("Share")`
- Expected: Share dialog opens (look for `role="dialog"` containing "Share map" or share link heading).

**Step 1.4 — Set visibility to Public (if not already)**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('[data-value="public"], input[value="public"]') !== null`
- If private: `mcp__playwright__browser_click` on the public radio/button to switch.

**Step 1.5 — Generate share link**
- Tool: `mcp__playwright__browser_click`
- Selector: `button:has-text("Generate share link"), button:has-text("Generate Share Link")`
- Wait: observe the Copy link button or share URL field appearing.
- Record the share token from the URL input for use in Section 3.

**Step 1.6 — Open Link Settings disclosure**
- Tool: `mcp__playwright__browser_click`
- Selector: `button:has-text("Link Settings"), [aria-expanded][aria-controls*="settings"], button:has-text("Settings")`
- Expected: Settings accordion/disclosure expands showing expiration + domain restriction controls.

**Step 1.7 — Enable "Restrict to domains" switch**
- Tool: `mcp__playwright__browser_click`
- Selector: `button[role="switch"][aria-label*="domain"], button[role="switch"]:has-text("domain"), input[type="checkbox"][id*="domain"]`
- Expected: Chip input row becomes visible with placeholder text "Paste a URL like https://example.com".

**Step 1.8 — Add canonical chip: type `Example.com` + Enter**
- Tool: `mcp__playwright__browser_type`
- Selector: `input[aria-label*="Allowed origin"], input[placeholder*="example.com"]`
- Text: `Example.com`
- Then: `mcp__playwright__browser_evaluate` — `document.querySelector('input[placeholder*="example.com"]').dispatchEvent(new KeyboardEvent('keydown', {key:'Enter',bubbles:true}))`
- Then: `mcp__playwright__browser_take_screenshot`
- Expected observable: Chip labeled `https://example.com` appears in the chip list (`role="list"` container). Input field is cleared. The chip text is ALL lowercase with `https://` scheme prepended — `Example.com` was canonicalized to `https://example.com`.

**Step 1.9 — Verify chip canonical form via evaluate**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `[...document.querySelectorAll('[role="listitem"]')].map(el => el.textContent?.trim()).filter(Boolean)`
- Expected: Array contains `"https://example.com"` (lowercase, no trailing slash, scheme added).

**Step 1.10 — Attempt wildcard origin: type `*` + Enter**
- Tool: `mcp__playwright__browser_type`
- Selector: `input[aria-label*="Allowed origin"], input[placeholder*="example.com"]`
- Text: `*`
- Then: `mcp__playwright__browser_evaluate` — same keydown Enter dispatch as Step 1.8.
- Then: `mcp__playwright__browser_take_screenshot`
- Expected observable: Inline error text "Wildcard origin not allowed" visible (as `text-xs text-destructive` paragraph below the input). NO new chip appears in the list. Chip count remains 1 (only `https://example.com`). No PATCH request fired for the wildcard.

**Step 1.11 — Confirm no wildcard chip via evaluate**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `[...document.querySelectorAll('[role="listitem"]')].map(el => el.textContent?.trim()).filter(s => s?.includes('*'))`
- Expected: Empty array `[]`.

**Step 1.12 — Remove the chip**
- Tool: `mcp__playwright__browser_click`
- Selector: `button[aria-label*="Remove https://example.com"], [role="listitem"] button[aria-label*="Remove"]`
- Then: `mcp__playwright__browser_evaluate`
- Script: `document.querySelectorAll('[role="listitem"]').length`
- Expected: Chip disappears; chip count = 0 (or the empty-state hint "No origins yet" is now visible).

**Step 1.13 — Take final screenshot of cleared chip list**
- Tool: `mcp__playwright__browser_take_screenshot`

### Disposition

| Sub-check | Expected | Observed | Status |
|-----------|----------|----------|--------|
| 1.8 — chip appears after `Example.com` + Enter | chip `https://example.com` visible; input cleared | | |
| 1.9 — canonical form evaluate | `["https://example.com"]` | | |
| 1.10 — wildcard `*` shows inline error | "Wildcard origin not allowed" text; no new chip | | |
| 1.11 — wildcard chip absent | `[]` | | |
| 1.12 — chip removed | chip count = 0 | | |

**Overall Section 1 disposition:** PASS / PARTIAL / FAIL

---

## Section 2: SHARE-04 — Expiration Preset Select

**REQ ID:** SHARE-04 (6 preset options, non-Custom auto-save, rawShareToken survival — Pitfall #6)
**Starting state:** Share dialog open from Section 1 (link settings expanded).

### Steps

**Step 2.1 — Locate the Expiration Select trigger**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('[role="combobox"][aria-label*="expir"], select[id*="expir"], button[role="combobox"]')?.textContent?.trim()`
- Expected: A Select trigger showing the current expiration value (e.g., "Never" or a date string).

**Step 2.2 — Open the expiration Select**
- Tool: `mcp__playwright__browser_click`
- Selector: First `button[role="combobox"]` inside the settings disclosure, OR the element identified in Step 2.1.
- Expected: Dropdown opens with options: Never, 1 day, 7 days, 30 days, 1 year, Custom date…

**Step 2.3 — Verify 6 preset options exist**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `[...document.querySelectorAll('[role="option"]')].map(el => el.textContent?.trim())`
- Expected: Array includes `"Never"`, `"1 day"`, `"7 days"`, `"30 days"`, `"1 year"`, `"Custom date…"`.

**Step 2.4 — Select "7 days"**
- Tool: `mcp__playwright__browser_click`
- Selector: `[role="option"]:has-text("7 days"), [role="option"][data-value="7d"]`
- Expected: Dropdown closes. Select trigger now displays "7 days". A success toast (`share.expirationUpdated` or "Expiration updated") appears briefly. No extra Save button click was required.

**Step 2.5 — Pitfall #6 verification — rawShareToken survives**
- Tool: `mcp__playwright__browser_take_screenshot`
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('[data-testid="copy-link-button"], button:has-text("Copy link"), button:has-text("Copy Link"), input[aria-label*="Share link"], input[aria-label*="share"]') !== null`
- Expected: `true` — the Copy link button (or share URL input) is still present, confirming `rawShareToken` was not cleared when the expiration preset was applied. This is the Pitfall #6 regression check.

**Step 2.6 — Select "Custom date…" to verify DatePicker reveals**
- Tool: `mcp__playwright__browser_click`
- Selector: Select trigger (same as Step 2.2).
- Then: `mcp__playwright__browser_click` on `[role="option"]:has-text("Custom date")`
- Expected: A `<input type="date">` field AND a "Save" button appear below the Select. The Copy link button remains visible.

**Step 2.7 — Take screenshot for Custom state**
- Tool: `mcp__playwright__browser_take_screenshot`

### Disposition

| Sub-check | Expected | Observed | Status |
|-----------|----------|----------|--------|
| 2.3 — 6 options in Select | Never, 1 day, 7 days, 30 days, 1 year, Custom date… | | |
| 2.4 — "7 days" auto-saves | Select shows "7 days"; no extra Save needed | | |
| 2.5 — Pitfall #6 rawShareToken survives | Copy link button still present | | |
| 2.6 — "Custom date…" reveals DatePicker + Save | date input + Save button visible | | |

**Overall Section 2 disposition:** PASS / PARTIAL / FAIL

---

## Section 3: SHARE-07 — Community-Edition Viewer Branding

**REQ ID:** SHARE-07 ("Powered by GeoLens" in embed mode; AppFooter in shared-link mode)
**Requires:** A valid share token from Section 1, Step 1.5.

### Steps

**Step 3.1 — Navigate to shared-link mode (non-embed)**

> If you did not record the share token in Step 1.5, extract it now:
> - Tool: `mcp__playwright__browser_evaluate`
> - Script: `document.querySelector('input[aria-label*="Share link"], input[aria-label*="share"]')?.value`
> - The token is the path segment in the URL — e.g. for `/m/abc123` the token is `abc123`.

- Tool: `mcp__playwright__browser_navigate`
- URL: `http://localhost:8080/m/<share-token>` (replace `<share-token>` with the actual token)
- Wait for the page to load (map canvas renders).

**Step 3.2 — Verify AppFooter "Powered by GeoLens" in non-embed mode (regression check)**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('footer, [data-testid="app-footer"], [class*="footer"]')?.textContent?.includes('GeoLens')`
- Expected: `true` — AppFooter is visible at the bottom with "Powered by GeoLens" text (existing behavior; regression check — this must NOT be broken by Phase 1137).

**Step 3.3 — Confirm inline branding overlay is ABSENT in non-embed mode**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('[data-testid="viewer-branding-overlay"]') !== null`
- Expected: `false` — the `showInlineBranding` prop is `false` for non-embed shared links; the inline overlay does not render.

**Step 3.4 — Navigate to embed mode**
- You need both share token and embed token. The embed token can be extracted from the embed code textarea in the Share dialog.
- Tool: `mcp__playwright__browser_navigate`
- URL: `http://localhost:8080/m/<share-token>?embed=true&et=<embed-token>`
- If you cannot recover the embed token from the dialog without reloading, navigate back to the builder first: `http://localhost:8080/maps/c39be324-6815-40e5-8143-00a2723827b2`
  - Open Share dialog
  - Locate the embed code textarea: `mcp__playwright__browser_evaluate` → `document.querySelector('textarea')?.value || document.querySelector('[aria-label*="embed code"], [aria-label*="Embed"]')?.value`
  - Parse `et=<value>` from the `<iframe src="...">` snippet string.
  - Then navigate to `http://localhost:8080/m/<share-token>?embed=true&et=<embed-token>`.

**Step 3.5 — Verify inline branding overlay IS present in embed mode**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('[data-testid="viewer-branding-overlay"]')?.textContent?.trim()`
- Expected: `"Powered by GeoLens"` (the `showInlineBranding` prop is `true` for embed mode per `PublicViewerPage.tsx:154`).

**Step 3.6 — Verify AppFooter is ABSENT in embed mode**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('footer, [data-testid="app-footer"]') === null`
- Expected: `true` — the `{!isEmbed && <AppFooter />}` gate suppresses AppFooter in embed mode.

**Step 3.7 — Take screenshot for visual diff**
- Tool: `mcp__playwright__browser_take_screenshot`
- Caption: "Embed mode — 'Powered by GeoLens' overlay bottom-left; no AppFooter"

### Disposition

| Sub-check | Expected | Observed | Status |
|-----------|----------|----------|--------|
| 3.2 — AppFooter present in non-embed mode | `true` | | |
| 3.3 — Inline overlay ABSENT in non-embed mode | `false` | | |
| 3.5 — Inline overlay PRESENT in embed mode | `"Powered by GeoLens"` | | |
| 3.6 — AppFooter ABSENT in embed mode | `true` | | |

**Enterprise note:** Enterprise suppression cannot be live-tested against the dev stack (community edition). The vitest pins in `ViewerMap.branding.test.tsx` (4 tests) cover both `isEnterprise: true` (branding absent) and `isEnterprise: false` (branding present) paths. Record as: "Enterprise verify: DEFERRED TO UNIT TESTS — 4 vitest pins PASS."

**Overall Section 3 disposition:** PASS / PARTIAL / FAIL

---

## Section 4: SHARE-09 — Legend + Title in Shared Viewer

**REQ ID:** SHARE-09 (MapLegend overlay + map title visible in viewer; export PNG composition)
**Starting URL:** `http://localhost:8080/m/<share-token>` (shared-link mode, not embed)

### Steps

**Step 4.1 — Navigate to shared viewer (if not already there)**
- Tool: `mcp__playwright__browser_navigate`
- URL: `http://localhost:8080/m/<share-token>` (same token as Section 3)

**Step 4.2 — Verify map title block renders**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('[data-testid="map-title"], h1, .map-title, [class*="title"]')?.textContent?.trim()`
- Expected: Non-empty string matching the map name (e.g., "Adirondack High Peaks — Terrain & Trails" or similar). The title block is rendered when `?title=true` (the default for shared links) and `map.name` is non-empty.

**Step 4.3 — Verify MapLegend overlay renders**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('[data-testid="map-legend"], [aria-label*="legend"], [class*="legend"]') !== null`
- Expected: `true` — the legend overlay is present when `?legend=true` (default).

**Step 4.4 — Verify legend has at least one row**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelectorAll('[data-testid="legend-row"], [class*="legend-row"], [class*="legend"] [class*="flex"]').length`
- Expected: `>= 1` — at least one layer row rendered in the legend (ADK map has multiple visible layers).

**Step 4.5 — Add `&legend=false` to URL and verify legend hides**
- Tool: `mcp__playwright__browser_navigate`
- URL: `http://localhost:8080/m/<share-token>?legend=false`
- Then: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('[data-testid="map-legend"], [aria-label*="legend"]') === null`
- Expected: `true` — legend overlay is hidden when `?legend=false`.

**Step 4.6 — Take screenshot (legend=false state)**
- Tool: `mcp__playwright__browser_take_screenshot`

**Step 4.7 — Export PNG verification (builder)**
Navigate back to builder, trigger an export, and visually verify:
- Tool: `mcp__playwright__browser_navigate`
- URL: `http://localhost:8080/maps/c39be324-6815-40e5-8143-00a2723827b2`
- Sign in if needed (Step 1.2 pattern).
- Tool: `mcp__playwright__browser_click`
- Selector: `button[aria-label*="Export"], button:has-text("Export"), [data-testid*="export"]`
- Then: `mcp__playwright__browser_click` on "Export PNG" or `button:has-text("PNG")`
- Expected: PNG download initiates. The vitest pins in `use-builder-save.test.ts` (SHARE-09 describe block, 4 tests) assert title + legend + branding composition. Record as: "Export PNG visual verify: unit tests PASS (title block + legend block + branding footer composition pinned by 4 regression tests in use-builder-save.test.ts). Live file inspection deferred — auto-download path varies by OS."

### Disposition

| Sub-check | Expected | Observed | Status |
|-----------|----------|----------|--------|
| 4.2 — Map title block renders | non-empty title text | | |
| 4.3 — MapLegend overlay present | `true` | | |
| 4.4 — Legend has rows | >= 1 row | | |
| 4.5 — `?legend=false` hides legend | `true` (legend absent) | | |
| 4.7 — Export PNG (unit-test coverage) | 4 vitest SHARE-09 pins PASS | | |

**Overall Section 4 disposition:** PASS / PARTIAL / FAIL

---

## Section 5: SHARE-03 — Iframe Embed-Preview Pane

**REQ ID:** SHARE-03 (collapsible iframe pane, `sandbox="allow-scripts"` only, SEC-07 contract)
**Starting URL:** `http://localhost:8080/maps/c39be324-6815-40e5-8143-00a2723827b2` (builder)

### Steps

**Step 5.1 — Navigate to builder and open Share dialog**
- Tool: `mcp__playwright__browser_navigate`
- URL: `http://localhost:8080/maps/c39be324-6815-40e5-8143-00a2723827b2`
- Tool: `mcp__playwright__browser_click`
- Selector: `button[aria-label="Share"], button:has-text("Share")`

**Step 5.2 — Ensure share + embed tokens exist**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('textarea, [aria-label*="embed code"]')?.value?.includes('<iframe') ?? false`
- If `false`: click "Generate share link" button first (Step 1.5 pattern). The embed token is created automatically for maps with non-public layers via `maybeCreateEmbedToken`.

**Step 5.3 — Verify Preview disclosure is COLLAPSED by default**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('button:has-text("Preview"), [aria-label*="Preview"], [data-testid="embed-preview-toggle"]')?.getAttribute('aria-expanded') ?? document.querySelector('[data-state="closed"]') !== null`
- Expected: The Preview toggle button is present and the pane is collapsed (no iframe visible yet).

**Step 5.4 — Click Preview to expand**
- Tool: `mcp__playwright__browser_click`
- Selector: `button:has-text("Preview"), [aria-label*="Preview"], [data-testid="embed-preview-toggle"]`
- Expected: The iframe pane expands. A loading spinner (Loader2 animate-spin) may briefly appear while the iframe loads.

**Step 5.5 — Wait briefly for iframe onLoad**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `new Promise(resolve => setTimeout(() => resolve(document.querySelector('[data-testid="share-preview-iframe"]')?.src || 'not found'), 2000))`
- Expected: Iframe src is set to a URL matching `http://localhost:8080/m/<token>?embed=true&et=<embed-token>`.

**Step 5.6 — Read iframe sandbox attribute — SEC-07 critical check**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('[data-testid="share-preview-iframe"]')?.sandbox?.value ?? document.querySelector('iframe[sandbox]')?.getAttribute('sandbox')`
- Expected: Exactly `"allow-scripts"` — NO `"allow-same-origin"` substring. This is the SEC-07 / M-70 hard invariant. A result of `"allow-scripts allow-same-origin"` is a FAIL.

**Step 5.7 — Verify iframe title accessibility attribute**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `document.querySelector('[data-testid="share-preview-iframe"]')?.title ?? document.querySelector('iframe[sandbox]')?.title`
- Expected: `"Map embed preview"` (from i18n key `share.iframePreviewTitle` with `defaultValue` fallback).

**Step 5.8 — Verify security indicator footer**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `[...document.querySelectorAll('*')].find(el => el.textContent?.includes('allow-scripts') && el.textContent?.includes('SEC-07'))?.textContent?.trim()`
- Expected: Non-null string containing `sandbox="allow-scripts"` and `SEC-07` — the security indicator footer below the iframe pane.

**Step 5.9 — Take screenshot of expanded iframe pane**
- Tool: `mcp__playwright__browser_take_screenshot`
- Caption: "SHARE-03 iframe pane expanded — sandbox=allow-scripts only; SEC-07 footer visible"

### Disposition

| Sub-check | Expected | Observed | Status |
|-----------|----------|----------|--------|
| 5.3 — Preview collapsed by default | toggle present; pane hidden | | |
| 5.5 — iframe src set to embed URL | `http://localhost:8080/m/<token>?embed=true&et=<et>` | | |
| 5.6 — sandbox = `"allow-scripts"` ONLY | `"allow-scripts"` (no `allow-same-origin`) | | |
| 5.7 — iframe title = `"Map embed preview"` | `"Map embed preview"` | | |
| 5.8 — SEC-07 footer visible | text contains `allow-scripts` + `SEC-07` | | |

**Overall Section 5 disposition:** PASS / PARTIAL / FAIL

---

## Section 6: Pitfall #7 — inflightEmbedCreate Race Dedupe

**REQ ID:** (Pitfall #7) — two concurrent "Generate Share Link" clicks fire exactly 1 POST
**Starting URL:** `http://localhost:8080/maps/c39be324-6815-40e5-8143-00a2723827b2` (builder)
**Note:** This is a best-effort UI smoke. The authoritative regression is `SharePanel.test.tsx` Pitfall #7 test (1/1 PASS). MCP smoke confirms the production code path matches the test.

### Steps

**Step 6.1 — Revoke existing share token (or use a fresh map without a share token)**
- Option A — Revoke via Share dialog:
  - Tool: `mcp__playwright__browser_click` on "Revoke" button inside the Share dialog (if a share link exists).
  - Confirm revocation dialog if shown.
- Option B — Navigate to a different map that has no share token.

**Step 6.2 — Open Share dialog and set public visibility**
- Tool: `mcp__playwright__browser_click` on Share button.
- Set visibility to Public if not already (Step 1.4 pattern).

**Step 6.3 — Fire two rapid clicks on "Generate share link"**
- Tool: `mcp__playwright__browser_evaluate`
- Script:
  ```javascript
  (() => {
    const btns = [...document.querySelectorAll('button')].filter(b =>
      b.textContent?.toLowerCase().includes('generate') ||
      b.textContent?.toLowerCase().includes('share link')
    );
    const btn = btns[0];
    if (!btn) return 'button not found';
    btn.click();
    btn.click();
    return `fired 2 clicks on: ${btn.textContent?.trim()}`;
  })()
  ```
- Expected return: `"fired 2 clicks on: Generate share link"` (or similar).

**Step 6.4 — Wait for the share token to appear**
- Tool: `mcp__playwright__browser_evaluate`
- Script: `new Promise(resolve => setTimeout(() => resolve(document.querySelector('input[aria-label*="Share link"], input[aria-label*="share"]')?.value || 'not found'), 3000))`
- Expected: A share URL is present (the POST completed successfully).

**Step 6.5 — Verify only 1 POST was fired via performance entries**
- Tool: `mcp__playwright__browser_evaluate`
- Script:
  ```javascript
  performance.getEntriesByType('resource')
    .filter(e => e.name.includes('/embed-tokens') || e.name.includes('/share-tokens') || e.name.includes('/shares'))
    .filter(e => (e).initiatorType === 'fetch')
    .map(e => ({ name: e.name, method: 'POST (inferred — fetch)', duration: Math.round(e.duration) + 'ms' }))
  ```
- Expected: 0 or 1 entries for the embed token creation path (POST). If 2 entries appear for the same endpoint with similar timestamps (within 500ms), that is a FAIL — the `inflightEmbedCreate` ref did not deduplicate.
- **Note:** The `performance.getEntriesByType` approach is best-effort for POST detection. If entries are unclear, fall back to `mcp__playwright__browser_console_messages` and look for log messages confirming embed token creation count.

**Step 6.6 — Take screenshot of final share state**
- Tool: `mcp__playwright__browser_take_screenshot`
- Caption: "Pitfall #7 race check — share link present, embed token created once"

### Disposition

| Sub-check | Expected | Observed | Status |
|-----------|----------|----------|--------|
| 6.3 — Two clicks dispatched | fires without JS error | | |
| 6.4 — Share token appears | URL input non-empty | | |
| 6.5 — POST count <= 1 for embed-token endpoint | 0 or 1 POST entries | | |
| Unit test coverage | SharePanel.test.tsx Pitfall #7: 1/1 PASS | report from `npm test -- SharePanel --run` | |

**Overall Section 6 disposition:** PASS / PARTIAL / FAIL

---

## Section 7: HARD-INVARIANT Regression Sweep

**Method:** `Bash` grep checks — NOT `mcp__playwright__*`. Run these directly.

**Invariant 1 — sandbox attribute count in SharePanel.tsx**
```bash
grep -cE 'sandbox="allow-scripts"' /Users/ishiland/Code/geolens/frontend/src/components/builder/SharePanel.tsx
```
Expected: `>= 2` (embed code snippet generator function + iframe pane JSX attribute; comment references are OK as additional occurrences).

**Invariant 2 — NO allow-same-origin as a JSX attribute**
```bash
grep -nE 'sandbox=["\x27][^"]*allow-same-origin' /Users/ishiland/Code/geolens/frontend/src/components/builder/SharePanel.tsx
```
Expected: Zero lines matching. Any match is a FAIL — SEC-07 / M-70 contract is broken.

**Invariant 3 — BuilderActionSource not imported in SharePanel or ViewerMap**
```bash
grep -c "BuilderActionSource" \
  /Users/ishiland/Code/geolens/frontend/src/components/builder/SharePanel.tsx \
  /Users/ishiland/Code/geolens/frontend/src/components/viewer/ViewerMap.tsx
```
Expected: `0` on both files (sum = 0). BuilderActionSource is a builder-only dispatch primitive — it must not appear in the share or viewer surfaces.

**Invariant 4 — SHARE-08 not touched (og_image / OG cards deferred to v1031)**
```bash
grep -c "SHARE-08\|og_image_uri\|og:image\|og_card" \
  /Users/ishiland/Code/geolens/frontend/src/components/builder/SharePanel.tsx \
  /Users/ishiland/Code/geolens/frontend/src/components/viewer/ViewerMap.tsx \
  /Users/ishiland/Code/geolens/frontend/src/pages/PublicViewerPage.tsx 2>/dev/null || echo "0"
```
Expected: `0` on all files. OG card / SHARE-08 work is deferred to v1031 per Phase 1133 audit. Any match is a FAIL.

**Invariant 5 — frame-ancestors never contains `*` in backend CSP**
```bash
grep -c "frame-ancestors '\*'\|frame-ancestors \*" \
  /Users/ishiland/Code/geolens/backend/app/modules/catalog/maps/router.py \
  /Users/ishiland/Code/geolens/backend/app/api/middleware/security.py 2>/dev/null || echo "0"
```
Expected: `0`. The `_build_frame_ancestors` helper and schema-layer rejection both ensure CSP frame-ancestors never emits `*`.

**Invariant 6 — inflightEmbedCreate ref present in SharePanel.tsx**
```bash
grep -c "inflightEmbedCreate" /Users/ishiland/Code/geolens/frontend/src/components/builder/SharePanel.tsx
```
Expected: `>= 3` (declaration, guard check, clear in finally).

**Invariant 7 — url-normalize.ts exports present**
```bash
grep -cE "export (class WildcardOriginError|function normalizeOrigin|function dedupeOrigins|class InvalidOriginError)" \
  /Users/ishiland/Code/geolens/frontend/src/lib/builder/url-normalize.ts
```
Expected: `4`.

### Disposition

| Invariant | Check | Expected | Observed | Status |
|-----------|-------|----------|----------|--------|
| INV-1 — sandbox="allow-scripts" count | grep -cE in SharePanel.tsx | >= 2 | | |
| INV-2 — allow-same-origin as JSX attr | grep -nE sandbox with allow-same-origin | 0 lines | | |
| INV-3 — BuilderActionSource absent | grep -c on SharePanel + ViewerMap | 0 | | |
| INV-4 — SHARE-08 / og_image not touched | grep -c across 3 files | 0 | | |
| INV-5 — frame-ancestors no-* | grep -c backend CSP files | 0 | | |
| INV-6 — inflightEmbedCreate ref present | grep -c in SharePanel.tsx | >= 3 | | |
| INV-7 — url-normalize.ts exports (4) | grep -cE export in url-normalize.ts | 4 | | |

**Overall Section 7 disposition:** PASS / PARTIAL / FAIL

---

## Section 8: Pitfall #8 — Canonical Form Round-Trip (regression pin)

**REQ ID:** SHARE-06 — `https://Example.com/` and `https://example.com` produce the same chip
**Method:** `Bash` unit test confirmation (Pitfall #8 is pinned by `url-normalize.test.ts` parity block).

```bash
cd /Users/ishiland/Code/geolens/frontend && npm test -- url-normalize --run 2>&1 | tail -20
```

Expected output contains: `22 passed` (or higher if tests were added). The parity block at describe `'parity with backend _normalize_origin'` covers the `https://Example.com/` → `https://example.com` case specifically.

| Check | Expected | Observed | Status |
|-------|----------|----------|--------|
| url-normalize.test.ts all pass | 22 passed | | |
| Pitfall #8 parity describe block present | "parity with backend _normalize_origin" in output | | |

---

## Section 9: Final Sign-Off Table

| Surface | REQ ID | Disposition | Observed (summary) | Date |
|---------|---------|--------------|--------------------|------|
| SHARE-02 chip add / canonicalize / remove | SHARE-02 | | | |
| SHARE-06 wildcard reject + dedupe | SHARE-06 | | | |
| SHARE-04 expiration presets (6 options + Pitfall #6 survival) | SHARE-04 | | | |
| SHARE-07 viewer branding — community embed mode | SHARE-07 | | | |
| SHARE-07 viewer branding — enterprise suppress | SHARE-07 (unit) | DEFERRED TO VITEST | 4 pins PASS | |
| SHARE-09 legend + title in shared viewer | SHARE-09 | | | |
| SHARE-09 export PNG composition | SHARE-09 (unit) | | | |
| SHARE-03 iframe pane — collapsible + sandbox attr | SHARE-03 | | | |
| Pitfall #6 rawShareToken survives expiration change | (Pitfall) | | | |
| Pitfall #7 inflightEmbedCreate race dedupe | (Pitfall) | | | |
| Pitfall #8 canonical form round-trip | (Pitfall) | | | |
| HARD-INVARIANT grep sweep (7 checks) | (Invariant) | | | |

---

## Aggregate Result

**Sign-off:** Orchestrator records overall disposition here on completion.

```
Aggregate: ___ / 12 items PASS, ___ PARTIAL, ___ FAIL
Overall Phase 1137 close status: PASS / PARTIAL / FAIL — [date]
```

If any item is FAIL or PARTIAL: propose a v1137.1 carry-forward plan naming the specific surface.
If all items are PASS or DEFERRED-TO-UNIT-TESTS (with confirmation that unit tests pass): Phase 1137 closes.

---

## Reference Materials

| Section | Source |
|---------|--------|
| SHARE-02 chip UI design | `1137-UI-SPEC.md` § Surface 1 |
| SHARE-04 expiration presets design | `1137-UI-SPEC.md` § Surface 2 |
| SHARE-07 viewer branding design | `1137-UI-SPEC.md` § Surface 3 |
| SHARE-09 legend + title design | `1137-UI-SPEC.md` § Surface 4 |
| SHARE-03 iframe preview design + SEC-07 contract | `1137-UI-SPEC.md` § Surface 5 |
| url-normalize helper (Pitfall #8) | `1137-01-SUMMARY.md` |
| Backend CSP no-* (Pitfall #8 backend) | `1137-02-SUMMARY.md` |
| ViewerMap branding + export PNG pins | `1137-03-SUMMARY.md` |
| Chip-based allowed-origins implementation | `1137-04-SUMMARY.md` |
| Expiration preset Select + Pitfall #6 docstrings | `1137-05-SUMMARY.md` |
| Iframe pane + inflightEmbedCreate (Pitfall #7) | `1137-06-SUMMARY.md` |
