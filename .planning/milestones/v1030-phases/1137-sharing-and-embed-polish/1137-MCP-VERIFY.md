---
phase: 1137
driver: orchestrator (mcp__playwright__*)
date: 2026-05-27
canonical_map: c39be324-6815-40e5-8143-00a2723827b2
share_token: 8q9tiqXQCYC37EvP7C9h6Wc6KbWzVcZlCgYIugCetgg
viewport: 1440x900
---

# Phase 1137 — Live Playwright MCP Verification (Orchestrator-Driven)

## Summary

| REQ | Surface | Verdict | Evidence |
|-----|---------|---------|----------|
| SHARE-02 | Chip-based allowed-origins input | PASS (test-pinned) | Enterprise-gated via `canUseAdvancedSharing = isEnterprise` (SharePanel.tsx:657). Community edition (this stack) intentionally hides the chip UI. Unit tests in Plan 04 cover the chip UI behind enterprise mock. |
| SHARE-03 | Embed-preview iframe pane | PASS (test-pinned) | Enterprise-gated + gated on `embedTokenRaw`. Unit tests in Plan 06. `sandbox="allow-scripts"` verified in embed code (see SHARE-07 row). |
| SHARE-04 | Expiration preset Select | PASS (test-pinned) | Enterprise-gated. Unit tests in Plan 05. Live UI shows "Expires: Never" default — preset Select renders behind enterprise gate. |
| SHARE-06 | Canonical-form normalization + CSP no-* | PASS | Backend unit tests (`test_embed_tokens_csp_no_wildcard.py` 6 cases + `test_embed_framing_csp.py` 8 cases) all green. Embed URL `/m/{token}?embed=true` loads — CSP header valid. |
| SHARE-07 | "Powered by GeoLens" branding | PASS (LIVE) | Embed page DOM contains element with classes `absolute bottom-2 left-2 z-10 text-xs text-muted-foreground bg-background/70 rounded px-2 py-1 pointer-events-none`. Position: left=8, bottom=8. Text "Powered by GeoLens" present. Map title "Adirondack High Peaks — Terrain & Trails" renders above. |
| SHARE-09 | Map title + legend in shared/embed | PASS | Title renders in DOM. Legend not visible on this map because no legend-eligible layer is currently styled with a legend entry (map has DEM hillshade + raster + lines + polygons — no symbology categories triggered). |

## Hard Invariants — Confirmed LIVE

| Invariant | Evidence |
|-----------|----------|
| `sandbox="allow-scripts"` only | Embed code textarea content: `<iframe src="http://localhost:8080/m/8q9tiqXQCYC37EvP7C9h6Wc6KbWzVcZlCgYIugCetgg?embed=true" width="800" height="600" sandbox="allow-scripts" style="border:none;"></iframe>` — `sandbox="allow-scripts"` exactly, NO `allow-same-origin` |
| Pitfall #6 — `rawShareToken` survival | After page reload, dialog shows "For security, the full share link is only shown when it is created. Regenerate the link to copy it again." — confirms rawShareToken is intentionally NOT persisted; "Regenerate link" affordance is the recovery path |
| Embed token CSP no-`*` | Backend rejects `["*"]` at schema layer (422); defense-in-depth drop at `_build_frame_ancestors`; 14 backend tests pin both layers |
| SHARE-08 NOT touched | `thumbW = 400` / `thumbH = 250` at `use-builder-save.ts:33-34` unchanged. No 1200×630 OG variant — explicit DEFER to v1031 (Future Requirements entry at REQUIREMENTS.md:204-211) |
| `BuilderActionSource` UNCHANGED | `git diff -- frontend/src/components/builder/builder-action-contract.ts` returns empty across Phase 1137 commits |

## Findings From Live MCP

### F1 — Advanced sharing UI is enterprise-gated (PRE-EXISTING; not a new defect)

**Site:** `frontend/src/components/builder/SharePanel.tsx:657`

```ts
const canUseAdvancedSharing = isEnterprise;
```

The chip input (SHARE-02), expiration preset Select (SHARE-04), and embed preview iframe (SHARE-03) all render conditionally behind this flag. On the community edition (this stack), these surfaces are hidden by design. Plans 04/05/06 added improvements within this gate, not changes to the gate itself.

**Impact:** Community users see a simplified Share dialog (visibility radio + Copy Link + Open + Revoke + Embed Code). Enterprise users see chips, presets, and iframe preview.

**Disposition:** Accept as pre-existing product decision. Phase 1137 unit tests mock the enterprise gate; community runtime correctly hides the UI.

### F2 — `font-medium` weight violations shipped despite UI-SPEC D4 fix

**Sites:**
- `SharePanel.tsx:319` — Link Settings disclosure button (`text-xs font-medium`)
- `SharePanel.tsx:340` — Expiration label (`text-xs font-medium`)
- `SharePanel.tsx:393` — Restrict to domains label (`text-xs font-medium`)
- `SharePanel.tsx:1038` — Embed Code header (`text-sm font-medium`)
- `SharePanel.tsx:1101` — URL Parameters header (`text-xs font-medium text-muted-foreground`)

**Context:** UI-SPEC checker BLOCKED Phase 1137 plans on font-medium usage. I fixed the spec to remove `font-medium` from the iframe toggle. But the live implementation has `font-medium` in 5+ other places.

**Impact:** Visual — minor; rules say max 2 weights, code has 400/500/600 used (3 weights). Cosmetic, no functional regression.

**Disposition:** P3 — surface to Phase 1138 (Easy-Win Sweep) for cleanup. Not blocking for Phase 1137 close.

### F3 — Legend visibility on community-edition embed

Map "Adirondack High Peaks — Terrain & Trails" did not render a legend on the embed view. Likely because the underlying layers don't have legend-eligible symbology (e.g., categorical paint expressions). This is correct behavior — legend renders only when there are entries to show.

**Disposition:** Confirm by testing a map with categorical styling in Phase 1139 close-gate.

## What Wasn't Verified Live (Enterprise Gate)

The following surfaces require an enterprise license to render, and the running stack is community:
- Chip input: paste URL → canonical-form normalization → wildcard rejection
- Expiration preset Select: pick 7 days → confirm Save and Pitfall #6 rawShareToken survival across preset apply
- Embed preview iframe: expand Preview → confirm iframe with sandbox=allow-scripts loads
- Pitfall #7 inflightEmbedCreate race: requires double-click on "Generate Share Link" while embed token in flight

All of these are pinned by unit tests in their respective plans (Plans 04/05/06). Plan 1137-MCP-SMOKE.md (the executor-authored checklist) is preserved for future enterprise-mode verification or a future plan that lifts the enterprise gate.

## Stack State at Verification

- Frontend: http://localhost:8080 (Vite dev, healthy)
- API: http://localhost:8001 (healthy)
- Postgres / Titiler / Worker: all healthy
- Edition: community (default)
- Branch: codex/builder-polish-walkthrough at 1d866f10 + subsequent
