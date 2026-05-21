# Quick Task 260324-cn5: Map chat @mention layers, slash commands, and prompt efficiency improvements - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Task Boundary

Add @mention layer references and slash commands to the map chat input, with inline autocomplete dropdown and smart contextual suggestions. Improve prompt efficiency by enriching @mentions with spatial context.

</domain>

<decisions>
## Implementation Decisions

### @mention Scope
- Layers only — @ references current map layers by name, inserts layer_id context so LLM knows which layer the user means

### Slash Commands
- Core set: /style, /filter, /label, /query, /add — maps directly to existing chat tools, covers 90% of use cases

### Autocomplete UX
- Inline dropdown appears below cursor on @ or / keystroke
- Arrow keys to navigate, Tab/Enter to select, Esc to dismiss
- Fuzzy matching on layer names and command names

### Map Creation Prompt
- No changes — keep map creation as a simple text prompt for now

### Smart Suggestions
- Context-aware prompt hints based on current layer/column types
- Examples: "show me hotspots", "compare these layers", "what's the distribution of X"
- Supplements existing suggestions (color by attribute, add labels, etc.)

### @mention Context Enrichment
- When user types @LayerName, inject a compact context block into the user message
- Include geometry type, feature count, and key column types
- Reduces reliance on system prompt for layer-specific context

### Claude's Discretion
- Exact slash command parameter syntax (e.g., /filter column > value vs natural language after /)
- Suggestion ranking/ordering algorithm
- Keyboard shortcut details beyond core nav (arrows, Tab, Esc)

</decisions>

<specifics>
## Specific Ideas

- Smart suggestions should be geometry-aware: point layers get "cluster", "heatmap" suggestions; polygon layers get "choropleth", "area analysis"
- /query should feel like a power-user shortcut — immediately signals data question intent to the LLM
- @mention enrichment format: `@LayerName [Polygon, 12,345 features, columns: name(text), value(numeric), date(timestamp)]`
- Consider column-type-aware suggestions: numeric columns → "distribution", "graduated color"; text columns → "categorical color", "filter by category"

</specifics>

<canonical_refs>
## Canonical References

No external specs — requirements fully captured in decisions above

</canonical_refs>
