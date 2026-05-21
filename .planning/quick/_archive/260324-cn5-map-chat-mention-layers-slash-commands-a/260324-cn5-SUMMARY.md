---
phase: quick-260324-cn5
plan: 01
subsystem: frontend/builder
tags: [chat, autocomplete, mention, slash-commands, enrichment, suggestions]
dependency_graph:
  requires: []
  provides: [chat-enrichment, chat-suggestions, mention-dropdown, chat-input]
  affects: [ChatPanel, builder-i18n]
tech_stack:
  added: []
  patterns: [trigger-detection, keyboard-nav-dropdown, message-enrichment]
key_files:
  created:
    - frontend/src/components/builder/chat-enrichment.ts
    - frontend/src/components/builder/chat-suggestions.ts
    - frontend/src/components/builder/MentionDropdown.tsx
    - frontend/src/components/builder/ChatInput.tsx
  modified:
    - frontend/src/components/builder/ChatPanel.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/fr/builder.json
decisions:
  - Bracket syntax @[Layer Name] for multi-word layer names, plain @Name for single-word
  - Slash commands as intent hints ([Intent: X]) not structured parameters
  - Custom trigger detection with simple includes() filtering (no fuzzy library needed for ~20 items)
  - Textarea with auto-resize replaces Input for multi-line support
  - enrichMessage applied to both streamChatMessage and sendChatMessage fallback paths
metrics:
  duration: 6min
  completed: 2026-03-24
---

# Quick Task 260324-cn5: Map Chat @Mention, Slash Commands & Smart Suggestions Summary

@mention layer references with context enrichment, /slash command intent hints, inline autocomplete dropdown, and geometry-aware smart suggestions for map builder chat input.

## What Was Built

### chat-enrichment.ts
- `enrichMessage(raw, layers)` parses @mentions (bracket and plain syntax) and /commands
- Resolved @mentions append `[Context: @Name = layer_id:X, geom, count, columns]` blocks
- Leading /style, /filter, /label, /query, /add commands prepend `[Intent: X]` prefix
- Deduplicates mentions by layer id; unresolvable mentions pass through

### chat-suggestions.ts
- `getSmartSuggestions(layers)` generates up to 4 geometry-aware and column-type-aware suggestions
- Point layers: heatmap, cluster, size-by-numeric
- Polygon layers: color-by-numeric, area labels
- LineString layers: width-by-numeric
- Column-aware: distribution for numeric, categories for text, date range for temporal
- Always ends with "Add another dataset" if room

### MentionDropdown.tsx
- Accessible listbox dropdown with role="listbox" and aria-selected
- Shows Layers icon for @ items, Terminal icon for / items
- Positioned above input (bottom-full), click-to-select with mouseDown preventDefault

### ChatInput.tsx
- Textarea with trigger detection for @ and / characters
- Builds layer items from MapLayerResponse props
- Arrow key navigation with wrapping, Tab/Enter to select, Esc to dismiss
- Enter sends message when dropdown is closed (no conflict)
- Auto-resize textarea up to 4 lines (96px max)
- Bracket insertion for layer names with spaces

### ChatPanel.tsx Integration
- Replaced Input with ChatInput component
- enrichMessage called before both streamChatMessage and sendChatMessage
- User sees original text in chat; LLM sees enriched text with context blocks
- Replaced getContextSuggestions with getSmartSuggestions (geometry/column aware)
- Removed old handleKeyDown (now internal to ChatInput)

### i18n
- Added chat.commands (style, filter, label, query, add) in all 4 locales
- Added chat.mentionHint in all 4 locales

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create chat-enrichment, chat-suggestions, MentionDropdown | c2c48786 | chat-enrichment.ts, chat-suggestions.ts, MentionDropdown.tsx |
| 2 | Create ChatInput with trigger detection | e4b0bbc9 | ChatInput.tsx |
| 3 | Integrate into ChatPanel, wire enrichment, i18n | 06c6ed11 | ChatPanel.tsx, 4 locale files |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed Unicode curly quotes in de/builder.json**
- **Found during:** Task 3
- **Issue:** German locale file had Unicode left/right double quotation marks (U+201C/U+201D) used as JSON structural quotes instead of ASCII double quotes, causing JSON parse failure
- **Fix:** Regenerated file from git original with new keys added via Python json module
- **Files modified:** frontend/src/i18n/locales/de/builder.json
- **Commit:** 06c6ed11

## Known Stubs

None -- all data flows are wired to live layer data from ChatPanel props.

## Verification

- TypeScript compiles cleanly (0 errors)
- All 63 test files pass (457 tests, 8 todo)
- All 4 locale JSON files validate

## Self-Check: PASSED
