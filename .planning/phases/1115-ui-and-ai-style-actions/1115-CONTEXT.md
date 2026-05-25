# Phase 1115: UI and AI Style Actions - Context

**Gathered:** 2026-05-25
**Status:** Ready for execution
**Mode:** Autonomous technical implementation

<domain>
## Phase Boundary

Align high-risk style action semantics after adapter migration. The main code path is AI chat style actions because backend `set_style` describes patch semantics while frontend currently treats `paint` as a full replacement. Manual editor controls are already routed through canonical `paint`/`style_config` updates and now converge through adapter ownership.
</domain>

<decisions>
## Implementation Decisions

### D-01: `set_style` Patches by Default

Frontend chat should merge `action.paint` into the current layer paint unless the action explicitly requests replacement.

### D-02: Explicit Clear Fields

AI actions need an explicit clear list because omitted keys must mean "preserve" under patch semantics. Add `clear_paint` and `replace_paint` to the backend schema, tool contract, frontend type, and frontend application logic.

### D-03: Data-Driven Chat Paint Preserves Unrelated Paint

Backend data-driven style actions return only the paint keys they own. The frontend should merge those keys into the current paint before replacing `style_config`.
</decisions>

<code_context>
## Existing Code Insights

- `ChatPanel.handleChatAction` calls `onPaintChange(action.layer_id, action.paint)` for `set_style`.
- `backend/app/processing/ai/tools.py` describes `set_style.paint` as properties "to set/override".
- `backend/app/processing/ai/schemas.py` has no clear/replace fields on `ChatAction`.
- `frontend/src/types/api.ts` mirrors `ChatAction` manually for frontend use.
- `ChatPanel.handleUndo` restores full snapshots via existing style handlers, which now converge through the reconciler.
</code_context>

<specifics>
## Specific Ideas

- Patch `ChatPanel` to compute next paint from latest `layersRef.current`.
- Treat null/undefined values in action paint as clears for robustness.
- Add frontend tests for patch preservation, explicit clear, explicit replace, and data-driven merge.
- Update backend tool descriptions and validation so `clear_paint` is filtered against geometry-specific paint allowlists.
</specifics>

<deferred>
## Deferred Ideas

- A separate backend `clear_style` tool may be clearer later, but a `clear_paint` field is enough for v1026 and avoids a broader tool dispatch expansion.
</deferred>
