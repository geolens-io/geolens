# Stack Research — v1030 Map Builder Polish Sweep

**Domain:** Internal product polish on an already-shipped, feature-rich map builder
**Researched:** 2026-05-27
**Confidence:** HIGH

## TL;DR

**v1030 is a polish milestone on top of a feature-complete stack. The honest answer to "what additions are needed?" is: almost nothing. Stay on the libraries you already have, use them more idiomatically through the v1027 controller / v1026 reconciler substrate, and resist net-new dependencies during a polish sweep.**

Three concrete recommendations, each scoped to one polish surface:

1. **Layer-type editor parity (fill/line/circle/symbol/heatmap/cluster/raster/basemap/DEM)** — stay on `maplibre-gl@^5.24.0` + `@vis.gl/react-maplibre@^8.1.0` + `chroma-js@^3.2.0` + `react-colorful@^5.6.1`. No version bumps, no new libs. Use the v1027 typed `LayerActions` boundary + v1026 style reconciler more idiomatically. Add zero net-new packages.
2. **AI-chat confirm-before-apply ergonomics** — keep `anthropic>=0.87` + `openai>=2.0,<3` (server-side already implements native tool use). On the frontend, do **NOT** add Vercel AI SDK. The existing SSE-driven `streamChatMessage` + `ChatAction` discriminated-union surface is the right substrate; the polish is action-tagging + UI-side preview/confirm, not transport-layer.
3. **Share/embed polish** — keep `navigator.clipboard.writeText` as-is (HTTPS-only is acceptable for this product; deployment is `localhost` for dev and HTTPS in prod). Defer adding `qrcode.react` / `react-qr-code` / OG-image generation unless the audit (Phase 1133) surfaces real demand. **Do NOT add Web Share API or `react-share` libraries.**

## v1030 Polish Surfaces vs. Stack Decisions

| Polish Surface | Stack Decision | Rationale |
|----------------|----------------|-----------|
| Layer-type editor parity (FillEditor, LineEditor, CircleEditor, SymbolEditor, HeatmapEditor, ClusterEditor, RasterEditor) | **No deps changed.** Use existing `LayerStyleEditor/` subdirectory split from v1010 PB-08 + v1027 typed `LayerActions` boundary. | Each render mode already has a sub-component (`FillEditor.tsx`, `LineEditor.tsx`, etc.); the polish is reconciling per-control coverage gaps surfaced by the Phase 1133 audit, not migrating to a new editor framework. |
| Basemap-as-group + DEM-as-raster sublayer behavior | **No deps changed.** v1008 `BasemapGroupRow` + DEM raster-layer model is the substrate. | The contract is jsonb-additive (per `paint._height_column` convention) — extend opaquely, no migration. |
| AI chat — "add a layer that shows X" / "which datasets cover Y" | **No new SDK.** Keep `anthropic>=0.87` + `openai>=2.0,<3`. Polish lives in the `ChatAction` action-tagging + frontend preview/confirm wrapper around the existing `handleChatAction()` reducer. | Backend `streaming.py` already implements native Anthropic tool use (`tool_use` block parsing, `has_tool_use` resume logic at lines 142, 197, 200, 333, 350, 354) + `tool_call_parser.py` shows OpenAI tool-calling parity. Vercel AI SDK would replace transport for no functional gain. |
| Sharing/embed polish (in-flight `3ed5ceb3`) | **No new deps.** Continue with `navigator.clipboard` + iframe `sandbox="allow-scripts"` snippet generator. | The existing `generateEmbedCode()` helper + `useCreateEmbedToken` / `useUpdateEmbedToken` / `useRevokeEmbedToken` mutations are the right substrate. Adding QR/OG image generation is scope-creep for a polish milestone. |
| Smaller-screen layout collisions (basemap selector double-X, lat/long pill overlay, right-sidebar overlap of zoom controls) | **No new deps.** Tailwind + existing v1011 `data-builder-canvas` scoped-CSS pattern. | The v1011 `data-builder-canvas="true"` attribute + scoped CSS rule is the load-bearing pattern (per [MEMORY entry](../../CLAUDE.md)) — extend with sibling responsive rules, do not introduce new responsive frameworks. |
| Easy-win UX enhancements from `todo.md` backlog | **No new deps unless an entry explicitly requires one.** | Polish milestones earn dependency additions through the audit-first walkthrough, not pre-emptively. |

## Current Stack (verified against `frontend/package.json` + `backend/pyproject.toml` 2026-05-27)

### Frontend — already in place, no changes needed

| Library | Current | Latest | Action |
|---------|---------|--------|--------|
| `maplibre-gl` | `^5.24.0` | 5.24.0 | **Stay.** v5.24.0 is the final v5 release (April 2026); v6 in development is not a polish target. |
| `@vis.gl/react-maplibre` | `^8.1.0` | 8.1.0 | **Stay.** v8 already supports MapLibre v5; no relevant new APIs since. |
| `react` / `react-dom` | `^19.2.0` / `^19.2.5` | 19.x | **Stay.** |
| `@tanstack/react-query` | `^5.100.9` | 5.x | **Stay.** All share/embed mutations already use it (`useCreateShareToken`, `useMapShareToken`, etc.). |
| `@tanstack/react-table` | `^8.21.3` | 8.x | **Stay.** |
| `@tanstack/react-virtual` | `^3.13.0` | 3.x | **Stay.** |
| `chroma-js` | `^3.2.0` | 3.x | **Stay.** Most feature-rich for data viz/gradients — ColorBrewer palettes, perceptual interpolation, chainable scales. Already used in `LineGradientControls.tsx` + `DataDrivenStyleEditor.tsx`. |
| `react-colorful` | `^5.6.1` | 5.6.1 | **Stay.** <5KB, accessible, sufficient for v1030. Do not migrate to `chromakit` (OKLCH is not a v1030 requirement — would add bundle weight for zero user-visible benefit). |
| `radix-ui` | `^1.4.3` | 1.x | **Stay.** Already powers `Dialog`, `DropdownMenu`, `Switch`, `Sheet` in the builder. |
| `lucide-react` | `^1.7.0` | 1.x | **Stay.** All icons in `ChatPanel.tsx` and `SharePanel.tsx` come from here. |
| `sonner` | `^2.0.7` | 2.x | **Stay.** Toast surface. |
| `react-i18next` | `^17.0.4` | 17.x | **Stay.** All polish strings flow through it. |
| `zustand` | `^5.0.11` | 5.x | **Stay.** Auth store + UI state. |
| `terra-draw` + `terra-draw-maplibre-gl-adapter` | `^1.28.8` / `^1.3.0` | current | **Stay.** Drawing tools are out-of-scope per v1030 anti-features (annotation/draw layer deferred). |
| `@dnd-kit/core` + `/sortable` + `/utilities` | `^6.3.1` / `^10.0.0` / `^3.2.2` | current | **Stay.** Unified-stack DnD substrate from v1008/v1009/v1011. |

### Backend — already in place, no changes needed

| Library | Current | Latest | Action |
|---------|---------|--------|--------|
| `anthropic` | `>=0.87.0` | 0.104.1 (2026-05-22) | **Stay.** The `>=0.87` floor allows any current version to install. The native tool-use streaming surface in `backend/app/processing/ai/streaming.py` (lines 103-234) works on both 0.87 and 0.104. **Do NOT pin to a specific newer version during a polish milestone** — risk-to-reward is bad. |
| `openai` | `>=2.0.0,<3` | 2.38.0 (2026-05-21) | **Stay.** Same logic — `>=2.0,<3` is current. Native structured outputs + tool calling already work via `tool_call_parser.py`. |
| `fastapi[standard]` | `>=0.115.0` | 0.115.x | **Stay.** SSE streaming via `sse-starlette>=3.3.2` is what powers `streamChatMessage`. |
| `sse-starlette` | `>=3.3.2` | 3.x | **Stay.** |

**Rationale for not bumping anthropic/openai SDKs:** The codebase uses primitive Messages API + ChatCompletions API. Tool use, streaming, structured outputs — all stable since well before 0.87 / 2.0 respectively. New SDK features (Workload Identity Federation, Managed Agents, AWS-region clients, thinking-token-count beta) are enterprise/agent-framework features GeoLens does not consume. Bumping introduces risk during a polish milestone for no functional benefit.

## What v1030 Polish Actually Needs

### 1. AI-chat confirm-before-apply (NEW capability — stack ALREADY supports)

The `ChatAction` discriminated union at `frontend/src/types/api.ts` + the `handleChatAction()` reducer at `ChatPanel.tsx:267-321` already supports all action types (`set_filter`, `set_style`, `set_data_driven_style`, `set_label`, `toggle_visibility`, `show_query_result`, `add_layer`, `remove_layer`, `set_opacity`). The v1030 polish is **purely UI-side**:

- **Action-preview surface:** between `actions` SSE event arrival and `handleChatAction()` dispatch, render a "Apply these N changes?" confirm card with diff-style rows (per existing v1009 BulkActionBar pattern from MapStackPanel deletes).
- **Undo extension:** `lastSnapshotRef` at `ChatPanel.tsx:172` already exists (v20260526-builder-audit BLD-20260526-04) — the multi-step undo is a follow-on polish, not a stack change.
- **No new dependencies.** This is `useState` + Radix `Dialog` (already in deps) + i18n strings (already in deps).

**Explicit non-recommendation:** Do NOT add Vercel AI SDK. It would replace the existing SSE transport (`streamChatMessage` at `frontend/src/api/maps.ts`) without adding capability. The backend `streaming.py` already implements the canonical Anthropic tool-use stream parser; the frontend already routes by `event` discriminator. Vercel AI SDK's `useChat` hook is for products that have NOT built this — GeoLens has.

### 2. Layer-type editor parity (audit-driven; stack ALREADY supports)

The Phase 1133 audit will surface gaps like "FillEditor exposes paint._height_column but HeatmapEditor does not expose paint.heatmap-color stops". Every such gap is a known-pattern fix within the existing editor subdirectory:

- `frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx`
- `frontend/src/components/builder/LayerStyleEditor/LineEditor.tsx`
- `frontend/src/components/builder/LayerStyleEditor/CircleEditor.tsx`
- `frontend/src/components/builder/LayerStyleEditor/SymbolEditor.tsx`
- `frontend/src/components/builder/LayerStyleEditor/HeatmapEditor.tsx`
- `frontend/src/components/builder/LayerStyleEditor/ClusterEditor.tsx`
- `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx`

Plus the data-driven and label editors (`DataDrivenStyleEditor.tsx`, `LabelEditor.tsx`) and the filter editor (`LayerFilterEditor.tsx`).

**Substrate this lands on:**
- v1027 typed `LayerActions` boundary (`builder-action-contract.ts`) — every editor calls through the same typed surface.
- v1026 shared style reconciler — paint changes flow through one reconciliation contract.
- v1010 `coalesceFrame` + 100/200ms debounces — hover-rate paint mutations are already throttled.

**No new dependencies.** The shape of every editor polish is "add a slider/select/colorpicker to the existing editor, wire it through the existing `onPaintChange` action."

### 3. Share/embed polish (in-flight; stack ALREADY supports)

`3ed5ceb3` already landed:
- Fresh-token persistence separated from persisted hint
- Embed-origin restrictions UX
- Expiration-clear vs. update messaging
- `handleRegenerateShareLink` + `handleRegenerateEmbedToken` flows
- Save-state warning banner

Remaining polish surfaces:
- **Copy-to-clipboard reliability** — `navigator.clipboard.writeText` works on HTTPS + localhost (covers dev + prod). Failure mode is a `toast.error(t('toasts.copyFailed'))` which already exists. **No fallback library needed.** If a user reports a non-HTTPS production deployment, address it as a deployment-config fix, not a stack addition.
- **Customization hints** — the existing `customizeTitle` block in `SharePanel.tsx:763-770` documents `zoom=N`, `center=lng,lat`, `legend=true|false`. Extend with i18n strings if the audit surfaces missing params; no new deps.

**Explicit non-recommendations** for share/embed:
- Do NOT add `qrcode.react` / `react-qr-code` / `qr-code-styling` — the embed iframe + share URL are the canonical outputs. QR codes are nice-to-have but not in the v1030 audit-driven scope. If demanded post-audit, `react-qr-code` is the lightest option (~6KB) — but defer.
- Do NOT add OG-image generation (`@vercel/og`, satori, sharp). The product is a SPA, not a static-site generator. Map screenshot OG-images are a Phase-x-many-from-now feature.
- Do NOT add `react-share` / `share-api-polyfill` / `react-web-share`. The product does not need "share to Twitter/WhatsApp" buttons — it needs reliable link + iframe copy, which `navigator.clipboard` already does.

## Installation

```bash
# No installs needed for v1030.
```

If the Phase 1133 audit surfaces a concrete need that the existing stack truly cannot serve, it gets added — but pre-emptively pinning new libraries during research is exactly what produces "we installed it and never used it" technical debt.

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Vercel AI SDK (`ai`, `@ai-sdk/anthropic`, `@ai-sdk/openai`) | Would replace existing SSE transport at `frontend/src/api/maps.ts` + `backend/app/processing/ai/streaming.py` for no functional gain. v1027 `ChatAction` discriminated-union surface is the right contract. Adding Vercel AI SDK = transport layer rewrite during a polish milestone. | Keep existing `streamChatMessage` SSE iterator + `handleChatAction` reducer. Polish action-confirmation in the UI layer above. |
| `qrcode.react` / `react-qr-code` / `qr-code-styling` | Scope-creep for polish milestone. Audit may surface demand but v1030 anti-features list excludes "new feature builds". | Defer until a real user request lands. |
| `@vercel/og` / `satori` / `sharp` (OG image generation) | GeoLens is not a static-site generator. Dynamic OG images for shared maps would require server-side MapLibre rendering or pre-baked screenshots — both are large milestones. | Defer. The existing share link + iframe embed are the canonical shareable artifacts. |
| `react-share` / `share-api-polyfill` / `react-web-share` | Web Share API is mobile-only and the product is desktop-first. The product needs reliable "copy link" and "copy iframe" — which `navigator.clipboard` already does. | `navigator.clipboard.writeText` (already in use). |
| `chromakit` / OKLCH color pickers | OKLCH is not a v1030 requirement. `react-colorful` (current dep) is <5KB and works for every existing color picker site. Replacing it would bloat bundle for zero user-visible benefit. | Keep `react-colorful`. |
| `culori` (OKLCH color manipulation) | `chroma-js` already provides ColorBrewer palettes + perceptual interpolation — sufficient for cartographic visualization. Switching color libraries mid-milestone is high-risk-low-reward. | Keep `chroma-js`. |
| `copy-to-clipboard` npm package | Adds 1KB + execCommand fallback for a deprecated API. Modern browsers all support `navigator.clipboard` on HTTPS + localhost; that covers GeoLens deployment surfaces. | `navigator.clipboard.writeText` directly. |
| Bumping `anthropic` to 0.104.x or `openai` to 2.38.x | The `>=0.87` and `>=2.0,<3` floors already allow the current versions. New SDK features (Managed Agents, AWS clients, Workload Identity) are not consumed by GeoLens. Pinning forward = risk for no gain during polish. | Keep current floors. Bump only if a sec advisory lands or a specific tool-use feature requires it. |
| Anthropic Agent SDK / OpenAI Agents SDK | "Agent" frameworks add multi-step planning loops, tool retry envelopes, and memory abstractions. v1030's chat already does one-shot tool use; agentic loops are an entirely different milestone. | Keep one-shot streaming tool use. |
| New responsive frameworks (e.g., Container Queries libraries) | v1011 established `data-builder-canvas="true"` scoped-CSS pattern. Adding a new responsive abstraction would re-litigate that decision during a polish milestone. | Use Tailwind + v1011 scoped-CSS pattern. |

## Integration Points (v1027 + v1026 + v1011 Substrate)

Every v1030 polish surface lands on already-established contracts:

| Polish | Lands on | Source-of-truth file |
|--------|----------|----------------------|
| Layer-type editor controls | v1027 `LayerActions` typed boundary | `frontend/src/components/builder/builder-action-contract.ts` |
| Layer-type editor paint changes | v1026 style reconciler | (shared reconciler module from v1026) |
| AI chat actions | v1027 `ChatAction` discriminated union | `frontend/src/types/api.ts` + `ChatPanel.tsx:267-321` |
| Hover-rate paint mutation throttling | v1010 `coalesceFrame` + 100/200ms debounces | `frontend/src/lib/builder/raf-coalesce.ts` |
| Basemap-as-group sublayer behavior | v1008 `BasemapGroupRow` + jsonb-additive `basemap_position` | (basemap-config jsonb model) |
| Drag-from-catalog cross-context | v1009 DndContext lift + v1011 `disabled.droppable` per-drag-source contract | (UnifiedStackPanel + dnd-kit registration sites) |
| Smaller-screen layout collisions | v1011 `data-builder-canvas="true"` scoped CSS pattern | `BuilderMap.tsx` + scoped CSS rule |
| Sharing/embed flow | `3ed5ceb3` polish (fresh-token persistence, allowed-origins, expiration messaging) | `frontend/src/components/builder/SharePanel.tsx` |
| Map auto-capture / thumbnail | v1010.2 SF-07 module-level `autoCapturedMapIds: Set` + StrictMode-safe predicate | (auto-capture predicate module) |
| Tile dedupe | v1010.2 SF-04 `getSourceIdForLayer` keyed by `dataset_table_name` (non-cluster) / per-layer (cluster) | `frontend/src/components/builder/map-sync.ts:374` |

**The pattern is consistent:** v1030 polish lands as "extend existing contract" not "introduce new contract."

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Stay on `maplibre-gl@^5.24.0` | Bump to v6 (in development) | When v6 ships and stabilizes (not 2026). Polish milestone is wrong time to track pre-release. |
| Stay on `anthropic>=0.87` floor | Pin to `>=0.104` | When a specific 0.104.x feature (e.g., thinking-token-count beta) becomes a product requirement. v1030 does not require thinking tokens. |
| Stay on `react-colorful` | Migrate to `chromakit` | When OKLCH color picking becomes a product requirement. v1030 does not require OKLCH. |
| Stay on `chroma-js` | Migrate to `culori` | When CSS Color Level 4 / wide-gamut display support becomes a requirement. v1030 does not. |
| Native `navigator.clipboard` | `copy-to-clipboard` package with execCommand fallback | When supporting non-HTTPS production deployments. GeoLens does not. |
| Existing SSE streaming | Vercel AI SDK `useChat` | When starting greenfield. GeoLens has working transport — switching during polish is destructive. |
| Iframe + URL copy | Web Share API (`navigator.share`) | When mobile-first sharing flow is a product requirement. GeoLens is desktop-first builder. |

## Version Compatibility

All current versions are mutually compatible (the stack ships on `localhost:8080` with this exact combination as of 2026-05-27). No changes proposed → no new compatibility risks introduced.

## Sources

### Verified against existing codebase (HIGH confidence)
- `/Users/ishiland/Code/geolens/frontend/package.json` (2026-05-27) — frontend deps verified
- `/Users/ishiland/Code/geolens/backend/pyproject.toml` (2026-05-27) — backend deps verified
- `/Users/ishiland/Code/geolens/frontend/src/components/builder/ChatPanel.tsx` — `ChatAction` discriminated union + `handleChatAction()` reducer
- `/Users/ishiland/Code/geolens/frontend/src/components/builder/SharePanel.tsx` — `generateEmbedCode()` + token regeneration UX
- `/Users/ishiland/Code/geolens/backend/app/processing/ai/streaming.py` — native Anthropic tool_use streaming parser
- `/Users/ishiland/Code/geolens/backend/app/processing/ai/tool_call_parser.py` — tool call parser
- `/Users/ishiland/Code/geolens/.planning/PROJECT.md` — milestone scope and substrate (v1026/v1027/v1029)

### External verification (MEDIUM confidence — version numbers only, not feature claims)
- [MapLibre GL JS Releases (GitHub)](https://github.com/maplibre/maplibre-gl-js/releases) — v5.24.0 confirmed as final v5 release, April 2026
- [@vis.gl/react-maplibre on npm](https://www.npmjs.com/package/@vis.gl/react-maplibre) — v8.1.0 confirmed latest
- [anthropic-sdk-python releases](https://github.com/anthropics/anthropic-sdk-python/releases) — v0.104.1 latest (2026-05-22); no breaking changes since 0.87 noted
- [OpenAI Python SDK on PyPI](https://pypi.org/project/openai/) — v2.38.0 latest (2026-05-21); 2.0-3.0 range still current
- [MapLibre Sprite spec](https://maplibre.org/maplibre-style-spec/sprite/) — SDF + sprite atlas patterns confirmed (no new APIs since v5.24)
- [Vercel AI SDK comparison guide (PkgPulse)](https://www.pkgpulse.com/guides/vercel-ai-sdk-vs-openai-sdk-vs-anthropic-sdk-2026) — confirms Vercel AI SDK adds transport abstraction, not new capability
- [chroma-js vs culori comparison (PkgPulse)](https://www.pkgpulse.com/blog/culori-vs-chroma-js-vs-tinycolor2-color-manipulation-javascript-2026) — chroma-js still recommended for data viz / map gradients

### Confidence assessment per claim
- **Current frontend/backend versions:** HIGH (read from package.json + pyproject.toml directly)
- **Latest available versions:** MEDIUM (verified via GitHub/npm/PyPI but pubdates can shift)
- **"No breaking changes" for anthropic 0.87 → 0.104.1:** MEDIUM (GitHub release notes do not enumerate breaking changes explicitly; major version remains 0.x, code paths in `streaming.py` use the stable Messages API surface)
- **Substrate integration points (v1027/v1026/v1011):** HIGH (codebase grep + PROJECT.md milestone records)
- **"Don't add X" recommendations:** HIGH (grounded in scope of polish milestone + anti-features list in PROJECT.md)

---
*Stack research for: v1030 Map Builder Polish Sweep*
*Researched: 2026-05-27*
*Bottom line: don't add anything. Use what's there better.*
