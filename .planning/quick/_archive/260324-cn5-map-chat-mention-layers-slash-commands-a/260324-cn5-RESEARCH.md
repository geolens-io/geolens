# Quick Task 260324-cn5: Map Chat @Mention & Slash Commands - Research

**Researched:** 2026-03-24
**Domain:** React inline autocomplete, prompt enrichment
**Confidence:** HIGH

## Summary

The current ChatPanel uses a simple `<Input>` (text input) with `onChange`/`onKeyDown`. Adding @mention and /slash autocomplete requires replacing or augmenting this with a component that can detect trigger characters, show a positioned dropdown, and insert completions. The most pragmatic approach for this codebase is a **custom implementation** using the existing `<textarea>` (or keeping `<input>`) with a floating dropdown, rather than pulling in a heavy library. The layer list is small (max ~15 layers) and slash commands are a fixed set of ~5, so the autocomplete data is trivial.

**Primary recommendation:** Build a custom `ChatInput` component with trigger detection (`@` and `/`), a `Popover`-style dropdown using Radix primitives already in the project, and keyboard navigation. No external library needed.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- @mention scope: Layers only -- references current map layers by name, inserts layer_id context
- Slash commands: /style, /filter, /label, /query, /add -- maps to existing chat tools
- Autocomplete UX: inline dropdown below cursor, arrow/Tab/Enter/Esc navigation, fuzzy matching
- Map creation prompt: no changes
- Smart suggestions: context-aware based on layer/column types, geometry-aware
- @mention enrichment: inject compact context block with geometry type, feature count, key columns

### Claude's Discretion
- Exact slash command parameter syntax (natural language after / vs structured params)
- Suggestion ranking/ordering algorithm
- Keyboard shortcut details beyond core nav

### Deferred Ideas (OUT OF SCOPE)
- None explicitly deferred
</user_constraints>

## Architecture Patterns

### Recommended Approach: Custom Trigger-Based Autocomplete

**Why not react-mentions or tributejs:**
- react-mentions forces a specific input component with its own styling, conflicts with the existing shadcn/ui Input and Tailwind patterns
- tributejs is designed for contenteditable, adds unnecessary complexity
- The autocomplete dataset is tiny (~15 layers + 5 commands) -- no need for a library

**Pattern:** Intercept keystrokes in the input, detect `@` or `/` at appropriate positions, show a floating menu, insert the selection.

### Component Structure
```
ChatPanel.tsx
  ChatInput.tsx (new)           -- textarea + trigger detection + state
  MentionDropdown.tsx (new)     -- floating list for @layers and /commands
  chat-suggestions.ts (new)    -- smart suggestion generation logic
```

### Pattern 1: Trigger Detection

**What:** Watch `input` value changes for trigger characters. Track whether user is "in a mention" or "in a command" by looking backwards from cursor position.

```typescript
interface TriggerState {
  type: '@' | '/' | null;
  startIndex: number;       // position of the trigger char
  query: string;            // text typed after trigger
}

function detectTrigger(value: string, cursorPos: number): TriggerState | null {
  // Walk backwards from cursor to find @ or /
  const beforeCursor = value.slice(0, cursorPos);

  // Check for @ trigger (not preceded by a word char)
  const atMatch = beforeCursor.match(/(^|[\s])@([^\s]*)$/);
  if (atMatch) {
    return {
      type: '@',
      startIndex: beforeCursor.lastIndexOf('@'),
      query: atMatch[2],
    };
  }

  // Check for / trigger (only at start of input or after whitespace)
  const slashMatch = beforeCursor.match(/(^|[\s])\/([^\s]*)$/);
  if (slashMatch) {
    return {
      type: '/',
      startIndex: beforeCursor.lastIndexOf('/'),
      query: slashMatch[2],
    };
  }

  return null;
}
```

### Pattern 2: Dropdown Positioning

**What:** Position the dropdown relative to the input element, not the cursor within text.

Since this is a single-line (or short) input, positioning is simple: render the dropdown directly above or below the input using absolute positioning. No need for `getCaretCoordinates` or similar complexity.

```typescript
// Dropdown rendered as a sibling to input, positioned with CSS
<div className="relative">
  <textarea ... />
  {trigger && (
    <div className="absolute bottom-full left-0 w-full mb-1 ...">
      {/* filtered items */}
    </div>
  )}
</div>
```

### Pattern 3: Keyboard Navigation in Dropdown

**What:** Arrow keys navigate the list, Tab/Enter select, Esc dismisses.

Key detail: the input's `onKeyDown` must intercept these keys when the dropdown is open, calling `e.preventDefault()` to avoid moving the cursor or submitting. The existing `handleKeyDown` with Enter-to-send must be gated on dropdown visibility.

```typescript
function handleKeyDown(e: React.KeyboardEvent) {
  if (dropdownOpen) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSelectedIndex(i => i + 1); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setSelectedIndex(i => i - 1); }
    if (e.key === 'Tab' || e.key === 'Enter') { e.preventDefault(); selectItem(); }
    if (e.key === 'Escape') { e.preventDefault(); closeDropdown(); }
    return;
  }
  // Original Enter-to-send behavior
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
}
```

### Pattern 4: Fuzzy Matching

**What:** Simple substring/prefix match on layer names and command names. No need for a fuzzy search library.

```typescript
function filterItems(items: Item[], query: string): Item[] {
  const q = query.toLowerCase();
  return items.filter(item => item.label.toLowerCase().includes(q));
}
```

### Pattern 5: Insertion on Selection

**What:** Replace the trigger + query text with the completed mention/command.

```typescript
function insertMention(value: string, trigger: TriggerState, replacement: string): string {
  return value.slice(0, trigger.startIndex) + replacement + ' ' + value.slice(trigger.startIndex + trigger.query.length + 1);
}
```

For @mentions, insert: `@LayerDisplayName` (keep human-readable in the input).
For /commands, insert: `/style ` (with trailing space, ready for natural language).

## @Mention Context Enrichment

### Frontend Enrichment (Before Send)

When the user submits a message containing `@LayerName`, the frontend should:

1. Parse all `@LayerName` tokens from the message
2. Match each to a layer from the `layers` prop
3. Append a compact context block to the message sent to the API

**Format (appended to user message):**
```
[Context: @Parcels = layer_id:abc-123, Polygon, 12,345 features, columns: owner(text), value(numeric), area(numeric)]
```

This is injected into the `message` field sent to `streamChatMessage()`. The LLM sees it as part of the user message and can reference the layer_id directly. No backend changes needed for this.

**Token efficiency:** A context block for one layer is ~30-50 tokens. Much cheaper than repeating the full system prompt layer descriptions. The system prompt already has full layer info, so the mention enrichment serves as an explicit "the user is talking about THIS layer" signal.

### Implementation Detail

```typescript
function enrichMessage(raw: string, layers: MapLayerResponse[]): string {
  const mentionRegex = /@([\w\s-]+?)(?=\s|$|@|\/)/g;
  const mentions: string[] = [];

  for (const match of raw.matchAll(mentionRegex)) {
    const name = match[1].trim();
    const layer = layers.find(l =>
      (l.display_name ?? l.dataset_name).toLowerCase() === name.toLowerCase()
    );
    if (layer) {
      const cols = (layer.dataset_column_info ?? [])
        .slice(0, 5)
        .map(c => `${c.name}(${c.type})`)
        .join(', ');
      const count = layer.dataset_feature_count
        ? `${layer.dataset_feature_count.toLocaleString()} features`
        : 'unknown count';
      mentions.push(
        `@${layer.display_name ?? layer.dataset_name} = layer_id:${layer.id}, ${layer.dataset_geometry_type ?? 'unknown'}, ${count}, columns: ${cols}`
      );
    }
  }

  if (mentions.length === 0) return raw;
  return `${raw}\n\n[Context: ${mentions.join(' | ')}]`;
}
```

## Slash Commands

### Command Definitions

| Command | Description | Behavior |
|---------|-------------|----------|
| `/style` | Change layer appearance | Prefixes message with style intent signal |
| `/filter` | Filter layer features | Prefixes message with filter intent signal |
| `/label` | Add/change labels | Prefixes message with label intent signal |
| `/query` | Ask data questions | Prefixes message with query_data intent signal |
| `/add` | Add a dataset | Prefixes message with add intent signal |

### Recommendation: Natural Language After Slash

Slash commands should act as **intent hints**, not structured parameters. The user types `/filter show parcels over $100k` and the entire string (minus the `/filter` prefix) goes to the LLM as the message, with an optional system-level hint prepended.

**Enrichment approach:** Prepend a bracketed hint to the user message:
```
[Intent: filter] show parcels over $100k
```

This nudges the LLM toward using the correct tool without requiring parameter parsing on the frontend. The LLM already knows how to pick tools from natural language.

## Smart Context-Aware Suggestions

### Geometry-Type Suggestions

| Geometry | Suggestions |
|----------|-------------|
| Point | "Create a heatmap", "Cluster points", "Size by {numeric_col}" |
| Polygon | "Choropleth by {numeric_col}", "Show area labels", "Color by {text_col}" |
| LineString | "Color by {text_col}", "Vary width by {numeric_col}" |
| Raster | "Adjust opacity", "Compare with..." |

### Column-Type Suggestions

| Column Type | Suggestions |
|-------------|-------------|
| numeric | "Distribution of {col}", "Graduated color by {col}", "Filter {col} > threshold" |
| text | "Categorical color by {col}", "Filter by {col} category", "Label by {col}" |
| timestamp | "Filter by date range", "Show recent features" |

### Implementation

Extend the existing `getContextSuggestions()` function in ChatPanel.tsx. It already checks for style_config, label_config, and filter presence. Add geometry-type and column-type awareness:

```typescript
function getContextSuggestions(layers: MapLayerResponse[]): string[] {
  const suggestions: string[] = [];

  for (const layer of layers) {
    const name = layer.display_name ?? layer.dataset_name;
    const geom = layer.dataset_geometry_type?.toLowerCase() ?? '';
    const numericCols = (layer.dataset_column_info ?? [])
      .filter(c => ['numeric', 'integer', 'float', 'double'].some(t => c.type.toLowerCase().includes(t)));
    const textCols = (layer.dataset_column_info ?? [])
      .filter(c => c.type.toLowerCase().includes('text') || c.type.toLowerCase().includes('varchar'));

    // Geometry-specific suggestions
    if (geom.includes('point') && !layer.style_config) {
      if (numericCols.length > 0) {
        suggestions.push(`Create a heatmap of @${name}`);
      }
    }
    if (geom.includes('polygon') && numericCols.length > 0 && !layer.style_config) {
      suggestions.push(`Color @${name} by ${numericCols[0].name}`);
    }
    // ... etc
  }

  return suggestions.slice(0, 4);
}
```

## Integration with Existing ChatPanel

### Minimal Change Strategy

1. **Extract input area** into a new `ChatInput` component that manages trigger state internally
2. **Props interface:** `{ value, onChange, onSubmit, layers, disabled, placeholder }`
3. **ChatPanel changes:** Replace `<Input>` + send button with `<ChatInput>`, move `handleKeyDown` Enter logic into `onSubmit`
4. **Message enrichment:** Add `enrichMessage()` call in `handleSend()` before passing to `streamChatMessage()`
5. **No backend changes needed** -- enrichment is purely frontend message preprocessing

### Input Element Choice

Keep `<input type="text">` (single line) or switch to `<textarea>`. Recommendation: switch to a `<textarea>` with `rows={1}` and auto-resize for multi-line support. This also future-proofs for longer prompts. The textarea auto-grows to fit content up to ~4 lines, then scrolls.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Fuzzy search | Full fuzzy algorithm (Levenshtein etc.) | Simple `includes()` substring match | Only ~20 items max, fuzzy is overkill |
| Dropdown positioning | Manual coordinate calculation | CSS `absolute` relative to input container | Input is fixed position in layout, no need for floating-ui |
| Rich text editing | contenteditable with spans | Plain textarea + visual hints | Complexity explosion; mentions are just text tokens |

## Common Pitfalls

### Pitfall 1: Enter Key Conflict
**What goes wrong:** Enter submits the chat when user means to select a dropdown item.
**How to avoid:** Gate Enter-to-send on `!dropdownOpen`. When dropdown is open, Enter selects the highlighted item instead.

### Pitfall 2: Layer Name Spaces
**What goes wrong:** `@My Layer Name` is ambiguous -- where does the mention end?
**How to avoid:** On insertion, use the full display name. On parsing, match against known layer names. Alternatively, wrap in brackets: `@[My Layer Name]` for unambiguous parsing. Recommendation: use the bracket syntax for names with spaces.

### Pitfall 3: Stale Layer References
**What goes wrong:** User types @mention, then removes the layer, then sends.
**How to avoid:** Validate mentions against current `layers` prop at send time. Drop unresolvable mentions silently (the LLM handles missing context gracefully).

### Pitfall 4: Cursor Position After Insert
**What goes wrong:** After inserting a mention, cursor jumps to wrong position.
**How to avoid:** Use `textarea.setSelectionRange()` after programmatic value change. React's controlled input will need a ref + `useEffect` to set cursor after re-render.

## Sources

### Primary (HIGH confidence)
- Direct code inspection: ChatPanel.tsx, maps.ts, chat_service.py, tools.py
- MapLayerResponse type definition in frontend/src/types/api.ts

### Secondary (MEDIUM confidence)
- React textarea autocomplete patterns -- standard DOM APIs (selectionStart, setSelectionRange)
- Radix UI primitives already available in the project (Popover, Command)

## Metadata

**Confidence breakdown:**
- Architecture: HIGH - straightforward React patterns, no novel technology
- @mention enrichment: HIGH - simple string preprocessing, no API changes
- Smart suggestions: HIGH - extends existing getContextSuggestions()
- Slash commands: HIGH - intent prefix approach avoids parsing complexity

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable patterns)
