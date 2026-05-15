---
phase: 1039-ux-audit-and-test-debt-closeout
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md
autonomous: true
requirements: [POL-12]
must_haves:
  truths:
    - "Reviewer opens `.planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md` and sees six top-level surface sections in order: UnifiedStackPanel, LayerEditorPanel, Add Dataset modal (DatasetSearchPanel), Settings scene (BasemapGroupEditorScene + LayerEditorPanel settings scene), SidebarRail, EmptyStackState."
    - "Each section contains a flat markdown table with columns `| ID | Finding | Severity | Fix priority |`. IDs use the prefix `AUD-NN` (zero-padded two-digit, sequential across the whole document, not per-section)."
    - "Every finding cites a specific code location (file path + line number or selector / state) — not a vague observation. The audit framework prohibits findings like 'spacing too tight' without a file:line anchor."
    - "Every finding is tagged `P0` (must fix before next release), `P1` (should fix this milestone), or `P2` (nice to have / defer)."
    - "Every finding's `Fix priority` column names the v1009 phase that should own the fix — either `1042` (spacing/density/states polish) or `1043` (error/empty-states/IA) — or `deferred` if the finding is out of v1009 scope."
    - "Findings reference `sketch-findings-geolens` tokens by name (e.g., `--surface-2`, `--surface-1`, `--motion-fast`, `--motion-base`, `--type-vector`, `--type-raster`, `--primary-50`, `--border`) where applicable, citing the token whose specification the finding is measured against."
    - "The audit closes with a `## P0 Roll-up` section listing every P0 ID + one-line summary so Phase 1042 and Phase 1043 can scope their plans against an explicit priority list (ROADMAP success criterion #4)."
    - "No source code is modified by this plan — the audit is read-only against the live codebase per CONTEXT.md hard constraints."
  artifacts:
    - path: ".planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md"
      provides: "The canonical UX-audit artifact driving Phase 1042/1043 priorities; contains all six surface sections plus the P0 roll-up."
      contains: "## P0 Roll-up"
      min_lines: 180
  key_links:
    - from: "BUILDER-UX-AUDIT.md findings"
      to: "specific source files (UnifiedStackPanel.tsx, StackRow.tsx, LayerEditorPanel.tsx, DatasetSearchPanel.tsx, BasemapGroupEditorScene.tsx, SidebarRail.tsx, EmptyStackState.tsx)"
      via: "file:line anchors in every finding's description"
      pattern: "\\.tsx:\\d+"
    - from: "BUILDER-UX-AUDIT.md `Fix priority` column"
      to: "Phase 1042 (spacing/density/states) or Phase 1043 (error/empty-states/IA)"
      via: "explicit phase number in every row"
      pattern: "104[23]|deferred"
    - from: "BUILDER-UX-AUDIT.md `## P0 Roll-up`"
      to: "v1009 milestone phase summaries"
      via: "P0 IDs are quotable by Phase 1042 and Phase 1043 plans"
      pattern: "AUD-\\d{2}"
---

<objective>
Produce `.planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md`
— the canonical UX-audit document for the v1008 unified-stack Map Builder.
This artifact drives Phase 1042 (spacing/density/states polish) and Phase 1043
(error/empty-states/IA cleanup) priorities. Without this document, those
phases have no source of truth for "what needs fixing"; with it, they can
plan against an explicit P0/P1 priority list cited by finding ID.

Purpose: POL-12 — enumerate every spacing/density/typography/state/error/empty/IA
finding across the six builder surfaces, with severity (P0/P1/P2) and a
fix-priority recommendation (which downstream phase, or deferred).

Scope (six surfaces, in audit order):
1. **UnifiedStackPanel** — the stack header (title + count + Settings + ＋ Add data), the listbox region, StackRow rows, basemap dock, folder-group children container, drag/drop affordances. File: `frontend/src/components/builder/UnifiedStackPanel.tsx` + `StackRow.tsx` + `BasemapGroupRow.tsx` + `FolderGroupRow.tsx`.
2. **LayerEditorPanel** — the 380px flyout, breadcrumb-style header, collapsible Filter/Labels/Source sections, drill-down `Sheet` overlay at <800px, footer button arrangement. File: `frontend/src/components/builder/LayerEditorPanel.tsx`.
3. **Add Dataset modal (`DatasetSearchPanel`)** — the search input, filter bar, results list, dataset preview, add-to-map CTA, modal chrome. File: `frontend/src/components/builder/DatasetSearchPanel.tsx`.
4. **Settings scene** — the basemap-group editor scene and the LayerEditorPanel settings scene route. Files: `frontend/src/components/builder/BasemapGroupEditorScene.tsx` + the settings-route branches of `LayerEditorPanel.tsx` and `SettingsEditorScene.tsx`.
5. **SidebarRail** — the 64px icon column shown at <1100px (Settings, ＋ Add data, layer icons). File: `frontend/src/components/builder/SidebarRail.tsx`.
6. **EmptyStackState** — heading + inline search + suggested-cards list + Browse-all link. File: `frontend/src/components/builder/EmptyStackState.tsx`.

Output: A single markdown file `BUILDER-UX-AUDIT.md` whose `## P0 Roll-up`
section is quotable by Phase 1042 and Phase 1043 plans without re-reading
the audit prose.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/STATE.md
@.planning/phases/1039-ux-audit-and-test-debt-closeout/1039-CONTEXT.md

# Design token / sketch reference (canonical for spacing/density/state observations)
@.claude/skills/sketch-findings-geolens/SKILL.md
@.claude/skills/sketch-findings-geolens/references/sidebar-structure.md
@.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md
@.claude/skills/sketch-findings-geolens/references/layer-editor-flyout.md
@.claude/skills/sketch-findings-geolens/references/empty-state.md
@.claude/skills/sketch-findings-geolens/references/responsive.md

# Six surfaces under audit (READ-ONLY — do NOT modify any of these)
@frontend/src/components/builder/UnifiedStackPanel.tsx
@frontend/src/components/builder/StackRow.tsx
@frontend/src/components/builder/BasemapGroupRow.tsx
@frontend/src/components/builder/FolderGroupRow.tsx
@frontend/src/components/builder/LayerEditorPanel.tsx
@frontend/src/components/builder/DatasetSearchPanel.tsx
@frontend/src/components/builder/BasemapGroupEditorScene.tsx
@frontend/src/components/builder/BasemapSublayerEditorScene.tsx
@frontend/src/components/builder/SettingsEditorScene.tsx
@frontend/src/components/builder/DEMEditorScene.tsx
@frontend/src/components/builder/SidebarRail.tsx
@frontend/src/components/builder/EmptyStackState.tsx
@frontend/src/components/builder/suggested-datasets.ts
@frontend/src/index.css

<interfaces>
<!-- Severity rubric for the auditor — apply consistently across every finding. -->

**P0** — Affects core flow correctness OR is visible in default state AND violates
the locked sketch decision. Examples:
- Drop-target affordance fails to render on the validated drag-into-group path.
- Header CTA fires no handler / fires the wrong handler.
- Suggested-cards in the empty state hide silently when SUGGESTED_DATASETS is
  populated but no UUID gate is met (and that gate is not documented).
- Async fetch shows a frozen surface with no spinner/skeleton (and the fetch
  takes >300ms).

**P1** — Visible polish gap inside the locked design vocabulary. Examples:
- Row vertical padding inconsistent across StackRow / BasemapGroupRow /
  FolderGroupRow (the unified stack must look unified).
- Hover/focus-visible/pressed states use different rings / different
  background tints across the six surfaces.
- Transition timing inconsistent (some `transition-colors`, some `duration-150`,
  some no transition at all on the same interactive element class).
- Section dividers in `LayerEditorPanel` use a different border token than the
  basemap-dock children container.

**P2** — Nice-to-have OR mobile-specific (`<800px`) beyond v1009 scope OR
defers to a future sketch round. Examples:
- Microinteraction polish (button press depth, kebab-menu open animation).
- Touch-target sizing on the rail (44px target compliance audit).
- Empty-state iconography refresh.

**Fix priority column** values: `1042` (spacing/density/typography/states/loading),
`1043` (error/empty-states/IA cleanup), or `deferred` (out of v1009 scope —
captured for backlog).

**Token reference (sketch-findings-geolens) — cite these by name in findings:**
- Surface: `--surface-1` (rows), `--surface-2` (hover / dock), `--surface-3` (subdued)
- Border: `--border`, `border-primary/30` (hover accent), `1px dashed var(--border)` (children container)
- Primary: `--primary`, `--primary-50` (selection / pressed tint), `--primary/30` (hover accent)
- Type colors: `--type-vector`, `--type-vector-bg`, `--type-raster`, `--type-raster-bg`
- Motion: `--motion-fast` (≤150ms hover/focus), `--motion-base` (200-300ms expand/collapse)
- Typography: text-xs (10-11px), text-sm (14px), font-semibold (header), font-medium (active)

**Audit framework — for each surface section:**

```markdown
## {Surface name}

**File(s):** `path/to/component.tsx` ({line range})

**Context:** {1-2 sentence framing of what this surface is and where in the builder it appears.}

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-NN | {Finding text with file:line anchor + concrete observation + token reference where applicable} | P0/P1/P2 | 1042 / 1043 / deferred |
```

**P0 Roll-up section format (at end of doc):**

```markdown
## P0 Roll-up

These findings MUST be addressed before v1009 milestone close.

- **AUD-NN** ({Surface}) — {one-line summary}. Owner: Phase {1042 or 1043}.
- **AUD-NN** ({Surface}) — {...}.
```

**Audit hygiene rules:**
- Every finding has a specific code anchor. Bad: "spacing too tight". Good: "Row vertical padding `p-2` (8px) on StackRow.tsx:140 produces ~32px total row height, which violates the 36-40px row-height target from `sketch-findings-geolens/references/layer-rows-and-groups.md`".
- Findings about state vocabulary cite the specific class strings being compared (e.g., `hover:bg-accent` vs `hover:bg-[var(--surface-2)]`).
- Findings about motion cite the actual transition class (or absence) — `transition-colors`, `duration-150`, etc.
- If a finding has no severity beyond "subjective preference," it does not belong in the audit; cut it.
- 12-30 findings total across all six surfaces is a healthy range. Below 8 suggests the audit was too shallow; above 40 suggests P2 noise — re-bucket aggressively.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Read the six audit surfaces + sketch-findings reference, build the finding list</name>
  <files>(read-only — no files modified)</files>
  <action>
Read each of the six audit surface source files ONCE (per the planner-anti-pattern rule "no re-reads"). After each file, extract every observation worth filing as a finding and write it directly into a working notes scratchpad (in-context, no separate file). For each candidate finding capture: surface, file:line, observation, severity bucket (P0/P1/P2), proposed fix-priority (1042/1043/deferred), and the token(s) referenced.

Reading order (top-to-bottom; do NOT loop back to re-read):

1. `frontend/src/components/builder/UnifiedStackPanel.tsx` (820 lines — read in two passes if needed: lines 1-410 then 411-820). Note: header chrome at ~656-685, listbox region at ~688-820, basemap dock rendering at ~340-460.
2. `frontend/src/components/builder/StackRow.tsx` (392 lines — single pass). Note: row anatomy at ~120-215, kebab menu at ~277-354, alertdialog at ~357-389.
3. `frontend/src/components/builder/BasemapGroupRow.tsx` and `FolderGroupRow.tsx` (companion group rows — compare row anatomy/density with `StackRow.tsx`).
4. `frontend/src/components/builder/LayerEditorPanel.tsx` (766 lines — read in two passes). Compare section anatomy across Filter/Labels/Source/Style/Source-list collapsibles.
5. `frontend/src/components/builder/DatasetSearchPanel.tsx` (604 lines — read in two passes). Pay attention to filter bar density (per project feedback `feedback_filter_bar_density.md`: "two-row filter bar is at visual limit; implement overflow before adding >3 type-specific controls").
6. `frontend/src/components/builder/BasemapGroupEditorScene.tsx` + `BasemapSublayerEditorScene.tsx` + `SettingsEditorScene.tsx` + `DEMEditorScene.tsx` (settings-route scenes). Compare scene chrome and footer button arrangements.
7. `frontend/src/components/builder/SidebarRail.tsx` (138 lines — single pass). Validate the 64px column matches the sketch (sources/008-responsive). Settings button at top, ＋ Add data below, then divider, then layer icons.
8. `frontend/src/components/builder/EmptyStackState.tsx` (256 lines — single pass). Pay attention to the `SUGGESTED_DATASETS` UUID gate (`UUID_RE` at line 46) and the silent-hide branches (lines 59-60); also note that `SUGGESTED_DATASETS` ships empty (`suggested-datasets.ts:32`) so the live default render shows heading + search + "Browse all" only — no suggestion cards.

While reading, also reference the sketch-findings tokens and decisions from:
- `.claude/skills/sketch-findings-geolens/references/sidebar-structure.md` — row anatomy + token specs
- `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` — caret semantics + group ops
- `.claude/skills/sketch-findings-geolens/references/layer-editor-flyout.md` — section chrome, footer button rules
- `.claude/skills/sketch-findings-geolens/references/empty-state.md` — catalog-first decisions
- `.claude/skills/sketch-findings-geolens/references/responsive.md` — rail/editor breakpoint rules

**While reading, apply these audit lenses to each surface (use them as a checklist — every surface should be evaluated against every lens):**

- **Spacing & density**: row heights, vertical padding, horizontal padding, gap-* values. Are they consistent across the six surfaces? Do they match the sketch tokens?
- **Typography hierarchy**: text-xs/text-sm/text-base, font-semibold/font-medium/font-normal, tracking-wide. Inconsistencies between surfaces?
- **State vocabulary**: hover, focus-visible, pressed, active, selected, dragging, disabled. Same tokens across surfaces? Same ring (`focus-visible:ring-2 focus-visible:ring-ring` vs other variants)?
- **Motion**: `transition-colors`, `duration-*`, `--motion-fast`, `--motion-base`. Same on equivalent interactions (hover, expand/collapse, slider drag)?
- **Loading affordances**: where async fetches happen (DatasetSearchPanel results, getDataset in EmptyStackState SuggestCard, column list in LayerFilterEditor, layer save) — is there always a skeleton/spinner/optimistic-UI affordance?
- **Error states**: every async failure point — recoverable with a localized message + retry, or silent fall-through?
- **Empty states**: every section that can be empty (Filter with no conditions, Labels off, Source columns empty, basemap-group with no customization, EmptyStackState) — intentional copy + iconography?
- **Information architecture**: section ordering inside `LayerEditorPanel` consistent across vector/raster/DEM/basemap? Scene transitions preserve scroll + focus?
- **Accessibility**: `aria-label`, `aria-selected`, `aria-multiselectable`, `aria-expanded`, keyboard reachability of all interactive elements?
- **Sketch fidelity**: validated decisions from `sketch-findings-geolens` honored? E.g., A-strict caret semantics, side-by-side flyout, basemap-as-group?

After reading all six surfaces, finalize the finding list. Aim for 12-30 findings total. Aggressively re-bucket P2 candidates that are subjective into "drop" or fold into a single roll-up P2 finding per surface. Aim for 3-6 P0 findings total across the whole audit — P0 is reserved for "must fix before v1009 close," not "is annoying."

DO NOT write to BUILDER-UX-AUDIT.md yet; that is Task 2. This task is the read-and-think pass.
  </action>
  <verify>
    <automated>echo "Read-and-think pass — verification gate is the populated finding list ready for Task 2. No file artifacts to assert."</automated>
  </verify>
  <done>
The auditor has a complete in-context finding list with 12-30 entries, 3-6 of which are P0. Every entry has a surface, file:line anchor, severity, fix-priority recommendation, and token reference (where applicable). The auditor is ready to write Task 2 in a single pass without re-reading source files.
  </done>
</task>

<task type="auto">
  <name>Task 2: Write `BUILDER-UX-AUDIT.md` with six surface sections + P0 Roll-up</name>
  <files>.planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md</files>
  <action>
Write the audit document in a single pass from the finding list assembled in Task 1. Follow the exact structure below — no preamble, no methodology essay, just the audit artifact.

**Document structure:**

```markdown
---
phase: 1039-ux-audit-and-test-debt-closeout
artifact: BUILDER-UX-AUDIT
requirement: POL-12
created: 2026-05-14
---

# Map Builder UX Audit — v1008 Surface Sweep

**Scope:** Six builder surfaces of the v1008 unified-stack Map Builder.
**Audited against:** `sketch-findings-geolens` token set + v1008 locked design decisions.
**Severity:** P0 = must fix before v1009 close · P1 = should fix this milestone · P2 = nice to have / defer.
**Fix priority column:** v1009 phase that should own the fix (1042 spacing/density/states; 1043 error/empty/IA) or `deferred`.

## Summary

- {N} findings across six surfaces.
- {N0} P0 / {N1} P1 / {N2} P2.
- Phase 1042 owns {N1042} findings (spacing/density/typography/states/loading).
- Phase 1043 owns {N1043} findings (error/empty-states/IA cleanup).
- {Ndef} findings deferred to backlog.

---

## UnifiedStackPanel

**File(s):** `frontend/src/components/builder/UnifiedStackPanel.tsx` (820 lines), `frontend/src/components/builder/StackRow.tsx` (392 lines), `frontend/src/components/builder/BasemapGroupRow.tsx`, `frontend/src/components/builder/FolderGroupRow.tsx`.

**Context:** The primary builder surface — header chrome with title/count/Settings/＋Add data, the listbox region rendering StackRow / BasemapGroupRow / FolderGroupRow, the basemap dock children container, drag/drop affordances (insertion line, group-tint).

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-01 | ... | P? | 1042 / 1043 / deferred |
| AUD-02 | ... | P? | ... |

---

## LayerEditorPanel

**File(s):** `frontend/src/components/builder/LayerEditorPanel.tsx` (766 lines).

**Context:** The 380px side-by-side flyout owning render-mode, paint, visibility, filter, labels, source, and delete; renders breadcrumb-style header at the top, collapsible sections in the middle, and footer button row at bottom.

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-NN | ... | ... | ... |

---

## Add Dataset Modal (DatasetSearchPanel)

**File(s):** `frontend/src/components/builder/DatasetSearchPanel.tsx` (604 lines).

**Context:** The catalog search/filter/preview/add-to-map modal triggered by ＋Add data, by the SidebarRail Add data icon, and by the EmptyStackState inline search + Browse all.

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-NN | ... | ... | ... |

---

## Settings Scene

**File(s):** `frontend/src/components/builder/BasemapGroupEditorScene.tsx` (248 lines), `frontend/src/components/builder/BasemapSublayerEditorScene.tsx`, `frontend/src/components/builder/SettingsEditorScene.tsx`, `frontend/src/components/builder/DEMEditorScene.tsx`, plus the settings-route branches of `LayerEditorPanel.tsx`.

**Context:** The non-layer scenes reached via ⚙ Settings — basemap group editor, basemap sublayer editor, terrain/widgets/projection settings, DEM editor.

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-NN | ... | ... | ... |

---

## SidebarRail

**File(s):** `frontend/src/components/builder/SidebarRail.tsx` (138 lines).

**Context:** The 64px icon column shown at <1100px (per `sketch-findings-geolens/references/responsive.md`) — Settings cog at top, ＋Add data icon below, divider, layer icons.

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-NN | ... | ... | ... |

---

## EmptyStackState

**File(s):** `frontend/src/components/builder/EmptyStackState.tsx` (256 lines), `frontend/src/components/builder/suggested-datasets.ts` (32 lines).

**Context:** The catalog-first empty state shown when `layers.length === 0` — heading + inline search + suggested-cards list + Browse-all link.

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-NN | ... | ... | ... |

---

## P0 Roll-up

These findings MUST be addressed before v1009 milestone close (ROADMAP success criterion #4).

- **AUD-NN** (Surface) — {one-line summary}. Owner: Phase {1042/1043}.
- **AUD-NN** (Surface) — {one-line summary}. Owner: Phase {1042/1043}.

## P1 Roll-up

Should fix this milestone if scope allows; otherwise defer to backlog with justification.

- **AUD-NN** (Surface) — ...
- ...

## Notes for downstream phases

- **Phase 1042** (spacing/density/states/loading) — total findings owned: {N1042}. Cite finding IDs in plan task descriptions.
- **Phase 1043** (error/empty/IA) — total findings owned: {N1043}. Cite finding IDs in plan task descriptions.
- **Backlog** — {Ndef} findings deferred. {one-sentence rationale per finding, OR a single bullet "see deferred column in tables above"}.
```

**Writing rules — enforce strictly:**

1. **Every finding cell starts with a file:line anchor.** Examples:
   - GOOD: "`UnifiedStackPanel.tsx:678` — Header `＋ Add data` `<Button>` uses `h-7` (28px) but `StackRow.tsx:200` opacity slider uses height `h-[22px]`; mixed sizing breaks the header/body density rhythm. Token target: header CTA `h-8` (32px) per sketch 001-A `${--surface-1}` row alignment."
   - BAD: "header button is too small"
2. **Use precise token names from `sketch-findings-geolens`.** If the finding observes a token absence or misuse, name the token: `--surface-2`, `--motion-fast`, `--primary-50`, etc.
3. **Severity must be defensible by the rubric.** If a finding could be P0 or P1, default to P1 unless it blocks a core flow.
4. **Fix priority must be one of `1042` / `1043` / `deferred`.** No other values. Spacing/density/typography/states/loading → 1042. Error states / empty states / IA / scene transitions → 1043. Anything mobile-specific or sketch-round-future → `deferred`.
5. **No empty cells.** If a column would be empty, the finding does not belong in the audit.
6. **Finding text is one sentence.** If you need two, you're either combining two findings (split them) or you're explaining methodology (move to the surface's `**Context:**` line).
7. **AUD IDs are sequential across the document, not per-section.** AUD-01 starts in UnifiedStackPanel; AUD-NN continues across all six sections without resetting. Zero-pad to two digits.
8. **No emoji.** Per the project-wide `/Users/ishiland/.claude/CLAUDE.md` style guide.
9. **The `## P0 Roll-up` section is the contract** with Phase 1042/1043. Every P0 ID from the tables must appear there; no P0 ID may be missing.
10. **DO NOT include source code blocks.** The audit is prose + tables. Code anchors are file:line references, not inlined snippets.

After writing, do a self-audit pass:
- Confirm 12-30 findings, 3-6 P0.
- Confirm every finding has a file:line anchor (grep the file for `\.tsx:\d+` and count matches ≥ finding count).
- Confirm P0 Roll-up enumerates every P0 ID from the tables.
- Confirm no emoji, no inlined code blocks (other than maybe inline `code` for class names / token names).
- Confirm `## Summary` count numbers match the actual table contents.
  </action>
  <verify>
    <automated>test -f .planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md && grep -c "^## " .planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md | awk '$1 >= 8 { exit 0 } { exit 1 }' && grep -cE "AUD-[0-9]{2}" .planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md | awk '$1 >= 12 { exit 0 } { exit 1 }' && grep -q "## P0 Roll-up" .planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md && ! grep -qE "(^|[^\\\\])TODO|FIXME|XXX" .planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md</automated>
  </verify>
  <done>
`BUILDER-UX-AUDIT.md` exists at the phase directory, contains at least 8 `##` headers (Summary, 6 surfaces, P0 Roll-up; bonus for P1 Roll-up and Notes), at least 12 `AUD-NN` IDs, a `## P0 Roll-up` section enumerating every P0 ID, and no TODO/FIXME placeholders. Self-audit pass confirms severity rubric is applied consistently and every finding has a file:line anchor.
  </done>
</task>

</tasks>

<verification>
1. `test -f .planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md` — file exists.
2. `grep -c "| AUD-" .planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md` — at least 12.
3. `grep -E "^## " .planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md` — confirms 6 surface sections + P0 Roll-up + Summary.
4. `grep -cE "P0\s*\|" .planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md` — count matches `## P0 Roll-up` bullet count.
5. `git diff --name-only frontend/src/components/builder/` — empty (no source modified).
6. Manual review: open the audit, confirm every finding has a `.tsx:NN` anchor, no emoji, severity column populated for every row, fix priority column populated for every row.
</verification>

<success_criteria>
- POL-12 satisfied: `BUILDER-UX-AUDIT.md` exists at `.planning/phases/1039-ux-audit-and-test-debt-closeout/`, enumerates findings across six surfaces with severity and fix priority per finding.
- ROADMAP success criterion #1 satisfied: reviewer can open the file and find P0/P1/P2-tagged findings across UnifiedStackPanel, LayerEditorPanel, Add Dataset modal, Settings scene, SidebarRail, EmptyStackState.
- ROADMAP success criterion #4 satisfied: `## P0 Roll-up` section explicitly lists every P0 ID with owner phase, ready for Phase 1042 and Phase 1043 to plan against.
- Audit is read-only — no source code modified by this plan.
- 12-30 findings total, 3-6 P0, every finding cites file:line and (where applicable) a sketch-findings-geolens token.
</success_criteria>

<output>
After completion, create `.planning/phases/1039-ux-audit-and-test-debt-closeout/1039-02-SUMMARY.md` containing:
- Total findings count and severity distribution (P0/P1/P2).
- Findings-per-surface count.
- The full `## P0 Roll-up` section quoted verbatim (so the phase summary that Phase 1044 reads can cite P0 IDs without re-reading the audit).
- Per-phase ownership counts: how many findings go to Phase 1042, Phase 1043, deferred.
- The "Production code unchanged" assertion: `git diff --name-only frontend/` should be empty.
</output>
