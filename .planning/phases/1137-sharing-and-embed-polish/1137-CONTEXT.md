---
phase: "1137"
name: "Sharing and Embed Polish"
gathered: "2026-05-27"
status: "Ready for planning"
mode: "Auto-generated (discuss skipped via workflow.skip_discuss)"
---

# Phase 1137: Sharing and Embed Polish — Context

<domain>
## Phase Boundary

Extend `3ed5ceb3`'s `rawShareToken` / `persistedShareTokenHint` separation with chip-based allowed-origins, expiration presets, "Powered by GeoLens" community-edition branding, legend+title in export, and a sandboxed iframe preview.

**Requirements:** SHARE-02, SHARE-03, SHARE-04, SHARE-06, SHARE-07, SHARE-09.

**5 ROADMAP success criteria:**
1. Allowed origins as removable chips after Save; chip input round-trips via PATCH `allowed_origins` with canonical-form normalization (trailing slash, case, port) — vitest (Pitfall #8); CSP `frame-ancestors` directive NEVER contains `*` (backend pin).
2. Expiration presets (1 day / 7 days / 30 days / 1 year / Never); custom-date stays as secondary; `rawShareToken` survival across dialog open/close preserved (Pitfall #6).
3. "Powered by GeoLens" in shared/embed views when `useEdition()` is community; suppressed under enterprise; map title + legend render in shared/embed/export PNG; `useEdition()` read on viewer + ViewerMap + thumbnail-capture.
4. Embed-preview iframe in SharePanel mirrors live embed at configured allowed-origin with `sandbox="allow-scripts"` only (NO `allow-same-origin` per SEC-07 / M-70 contract at `SharePanel.tsx:36`). If Phase 1133 audit deferred SHARE-03 → document as deferred-with-rationale.
5. Embed-token in-flight race closed via `inflightEmbedCreate` ref mirroring ChatPanel's `inflightRef` (Pitfall #7); race regression pin in `SharePanel.test.tsx`.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices at Claude's discretion (discuss skipped). ROADMAP + Phase 1133 audit + UI-SPEC are the spec.

### Key Pre-Decided Anchors

- **SHARE-03 iframe sandbox: KEEP per Phase 1133 audit** (`1133-BUILDER-WALKTHROUGH-AUDIT.md`). `sandbox="allow-scripts"` only — viewer authenticates via `et=` query param, no `allow-same-origin` needed.
- **`rawShareToken` survival (Pitfall #6):** `useShareDialog` keeps `rawShareToken` in state across dialog open/close cycles per `3ed5ceb3`. Docstring + regression pin asserts contract.
- **Pitfall #7 (race):** new `inflightEmbedCreate` ref pattern mirrors `ChatPanel.tsx`'s `inflightRef` (lifted in v1010.2). Single-fire guard for embed-token creation.
- **Pitfall #8 (canonical form):** chip input normalizes scheme/host/port/trailing-slash before saving. `https://Example.com/` and `https://example.com` produce SAME canonical chip.
- **CSP frame-ancestors NEVER `*`:** backend pin via test asserting no `*` substring in CSP header for share routes.
- **`useEdition()` integration:** read at viewer + ViewerMap + thumbnail-capture paths. Community → branding shown. Enterprise → branding suppressed.
- **No new BuilderActionSource / BuilderLayerAction widening.**

</decisions>

<code_context>
## Existing Code Insights

Anchor files:
- `frontend/src/components/builder/SharePanel.tsx` (current state; `rawShareToken`/`persistedShareTokenHint` separation lives here; `sandbox="allow-scripts"` at line ~36)
- `frontend/src/hooks/use-share-dialog.ts` (or similar — dialog state, rawShareToken)
- `frontend/src/hooks/use-edition.ts` (or use-edition.tsx — community/enterprise lookup)
- `frontend/src/components/maps/ViewerMap.tsx` (branding suppression target)
- `frontend/src/components/maps/ThumbnailCapture.tsx` (or use-builder-save.ts thumbnail path — branding suppression target)
- `frontend/src/lib/builder/url-normalize.ts` (new helper for canonical-form normalization, if not already exists)
- `backend/app/api/shares.py` (or maps router — PATCH allowed_origins; CSP header)
- `backend/tests/test_csp.py` (frame-ancestors no-asterisk regression pin)

</code_context>

<specifics>
## Specific Ideas

- **Chip input:** existing shadcn Input + per-chip removable Badge; submit on Enter or comma; normalize+dedupe on commit.
- **Expiration presets:** Select with 5 options + "Custom" option that reveals existing DatePicker.
- **Branding:** small text "Powered by GeoLens" bottom-left of viewer / embed; suppress when `edition.tier === 'enterprise'`.
- **Legend in export:** existing legend component; when exporting PNG, render legend overlay + title overlay before screenshot.
- **`inflightEmbedCreate` ref:** `useRef<Promise<EmbedToken> | null>(null)`. On submit: if ref.current is non-null, return it. On settle: clear ref.

</specifics>

<deferred>
## Deferred Ideas

- SHARE-08 (1200×630 OG-cards): DEFERRED to v1031 per Phase 1133 audit. NOT touched here.

</deferred>
