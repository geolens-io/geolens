---
phase: "1138"
name: "Easy-Win Sweep"
gathered: "2026-05-27"
status: "Ready for planning"
mode: "Auto-generated (discuss skipped via workflow.skip_discuss)"
---

# Phase 1138: Easy-Win Sweep — Context

<domain>
## Phase Boundary

Close cross-cutting easy-win items that don't fit any single bucket: keyboard shortcut, popup affordances, empty-layer state.

**Requirements:** EASY-02, EASY-11, EASY-18.

**4 ROADMAP success criteria:**
1. **EASY-02 Cmd/Ctrl+S triggers Save** — when builder focused, visible toast on success; gated by map-builder route; no-op when dialog/modal open; no conflict with browser save UI (preventDefault).
2. **EASY-11 Popup URL/media handling** — PopupConfigEditor + popup renderer detect URLs (auto-linkify), basic media (.jpg/.png/.mp4 + YouTube), `{column}` token syntax documented.
3. **EASY-18 Empty-layer state** — when layer renders 0 features (filter eliminated all OR empty source), LayerEditorPanel shows "0 features — check your filter" hint + "Clear filter" button that dispatches through BuilderLayerAction (no bypass).
4. **Phase 1139 close-gate precedent (Pitfall #14):** Live Playwright MCP at 800px viewport verifies all three easy-wins do not regress any Phase 1134/1136 layout fix.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All choices at Claude's discretion (discuss skipped). ROADMAP + Phase 1133 audit are the spec.

### Pre-Decided Anchors
- **No `BuilderLayerAction` widening:** Clear-filter dispatches through existing typed action.
- **Cmd/Ctrl+S preventDefault:** Stop browser's "Save Page As" dialog when builder focused.
- **Scope:** route-gated keyboard listener (mount/unmount per route).
- **Media detection:** extension match (case-insensitive) for `.jpg|.jpeg|.png|.gif|.webp|.mp4|.webm` + YouTube URL pattern.
- **`{column}` substitution:** existing template syntax in popup_config; document in PopupConfigEditor with helper text and example.
- **Pitfall #14 (no "small CSS-only change" exception to MCP re-verify):** Even trivial changes must be MCP-verified at 800px.

</decisions>

<code_context>
## Existing Code Insights

Anchor files:
- `frontend/src/pages/MapBuilderPage.tsx` (Cmd/Ctrl+S keyboard listener target; useEffect with route gate)
- `frontend/src/components/builder/PopupConfigEditor.tsx` (URL/media detection + token doc)
- `frontend/src/components/builder/popup-renderer.tsx` or equivalent (live popup body renderer)
- `frontend/src/components/builder/LayerEditorPanel.tsx` (empty-state hint + Clear filter button)
- `frontend/src/builder/dispatchLayerAction.ts` (Clear filter must dispatch through this; existing set_filter variant likely handles clear via filter=null)
- `frontend/src/components/builder/hooks/use-builder-save.ts` (save handler — already exists; keyboard binding fires this)

</code_context>

<specifics>
## Specific Ideas

- **Cmd/Ctrl+S:** `useEffect` mounts global keydown listener with `if (e.metaKey || e.ctrlKey) && e.key === 's'` → `preventDefault()` + invoke save handler. Skip when `document.querySelector('[role="dialog"][data-state="open"]')` exists.
- **URL auto-linkify:** simple regex `/https?:\/\/\S+/gi` in popup renderer; wrap matches in `<a href={url} target="_blank" rel="noopener noreferrer">`.
- **Media detection:** test URL against extension pattern; if image → `<img>`, if video → `<video controls>`, if YouTube → embedded iframe.
- **Empty-layer hint:** check `layer.feature_count === 0` OR `result.rows === 0` after filter. Render hint with destructive-tinted color + Clear filter button.

</specifics>

<deferred>
## Deferred Ideas

None.

</deferred>
