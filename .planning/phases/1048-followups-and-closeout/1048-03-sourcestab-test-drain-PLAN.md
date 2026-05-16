---
phase: 1048-followups-and-closeout
plan: 03
type: execute
wave: 3
depends_on:
  - 1048-02
files_modified:
  - frontend/src/components/dataset/__tests__/SourcesTab.test.tsx
  - .planning/backlog/SourcesTab-test-todos.md
autonomous: true
requirements:
  - FOLLOWUP-03
must_haves:
  truths:
    - "All 8 backlog items in .planning/backlog/SourcesTab-test-todos.md have a final disposition: either shipped as a live vitest case OR migrated-with-rationale."
    - "The net it.todo count in SourcesTab.test.tsx remains at zero (or the existing baseline if it was already zero) — no new it.todo entries introduced."
    - "Each shipped test exercises a real assertion against the current SourcesTab component."
    - "Vitest builder + dataset suite green after all changes."
  artifacts:
    - path: frontend/src/components/dataset/__tests__/SourcesTab.test.tsx
      provides: "Up to 8 new live vitest cases (one per backlog item)"
      min_lines: 200
    - path: .planning/backlog/SourcesTab-test-todos.md
      provides: "Updated checklist where every item is checked-off OR rewritten with migration rationale"
      contains: "shipped|migrated"
  key_links:
    - from: frontend/src/components/dataset/__tests__/SourcesTab.test.tsx
      to: frontend/src/components/dataset/tabs/SourcesTab.tsx
      via: "import + render + screen queries"
      pattern: "import.*SourcesTab"
---

<objective>
Drain the 8-item `it.todo` backlog at `.planning/backlog/SourcesTab-test-todos.md` to zero. Default: ship each item as a live vitest case. Migrate-with-rationale only when the underlying behavior has materially shifted OR the test would require fixtures/utilities that exceed the closeout budget.

Purpose: FOLLOWUP-03 — the 8 deferred tests were migrated from inline `it.todo(...)` placeholders during Phase 278 (TEST-07). Closeout requires the net `it.todo` count for SourcesTab to be zero. Either we ship the test or we explicitly migrate it to permanent backlog with stated rationale.

Output: New vitest cases in `SourcesTab.test.tsx`; updated backlog document with per-item final disposition; vitest green.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/1048-followups-and-closeout/1048-CONTEXT.md
@.planning/backlog/SourcesTab-test-todos.md

<interfaces>
<!-- Test harness shape + component-under-test entry points. -->

From frontend/src/components/dataset/__tests__/SourcesTab.test.tsx (existing, lines 1–140):
- Mocks: `useVrtSources, useAddVrtSource, useRemoveVrtSource, useVrtStatus, useVrtGenerations, useRegenerateVrt` from `@/components/import/hooks/use-vrt`
- Fixtures already in scope: `mockDataset: DatasetResponse` (a vrt dataset with `record_type: 'vrt_dataset'`), `mockSources` (array of 2 source records with `dataset_id, title, position, band_count, resolution_x, resolution_y, crs_epsg, extent_bbox`)
- Mutation helpers: `mockAddMutation, mockRemoveMutation, mockRegenerateMutation` — each with `mutateAsync: vi.fn(), isPending: false`
- `beforeEach` block wires all 6 hooks to default mocked returns. Override per-test via `vi.mocked(useVrtStatus).mockReturnValue({ ... })` etc.
- Test harness: `import { render } from '@/test/test-utils'` (wraps with i18n + query client per existing pattern). `import { screen } from '@testing-library/react'`.
- Existing live test pattern at line 134: `it('uses centralized semantic colors for VRT generation badges (A11Y-04)', () => { vi.mocked(...).mockReturnValue(...); render(<SourcesTab dataset={mockDataset} />); ... })`

From frontend/src/components/dataset/tabs/SourcesTab.tsx (510 LOC — read full file to confirm prop shape):
- Component is `SourcesTab({ dataset }: { dataset: DatasetResponse })` — single prop
- Behavior surface (matched to backlog items):
  1. "renders source table with rows in position order" → sort `mockSources` by `position` ascending; assert DOM order matches
  2. "source title is a clickable link to /datasets/{dataset_id}" → assert `<a href="/datasets/src-1">Source COG A</a>` or `getByRole('link', { name: /Source COG A/ })`
  3. "shows regenerating banner when status === 'regenerating'" → override `useVrtStatus` to return `{ status: 'regenerating', ... }`; assert banner text from i18n key
  4. "shows failed banner when status === 'failed'" → analogous
  5. "disables add/remove when regenerating" → override status; assert `getByRole('button', { name: /add|remove/i })` is `disabled`
  6. "remove button triggers confirm dialog" → click remove; assert a dialog with role=alertdialog or a `getByText(/are you sure/i)` appears
  7. "disables remove when only 2 sources" → 2 sources is the floor (VRT requires ≥2); assert remove buttons disabled
  8. "add source picker filters out already-linked sources" → open the add-picker; assert `mockSources[0].dataset_id` does NOT appear in the picker's candidate list

From `.planning/backlog/SourcesTab-test-todos.md`:
- 8 checklist items mirrored above. After this plan ships, every `- [ ]` should become `- [x] shipped (test name)` OR `- [ ] migrated — <rationale>`.
- The file's footer says "When all 8 are landed, delete this file." Honor that: if all 8 ship, delete the file. If any migrate, keep the file with only the migrated items + a final note: "Remaining items are permanent backlog — no longer tracked as deferred test debt."
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Ship live vitest cases for SourcesTab backlog items</name>
  <files>
    frontend/src/components/dataset/__tests__/SourcesTab.test.tsx
  </files>
  <read_first>
    - frontend/src/components/dataset/__tests__/SourcesTab.test.tsx (full file — read in one pass to understand the existing harness)
    - frontend/src/components/dataset/tabs/SourcesTab.tsx (full file, 510 LOC — read in one pass; if needed split into 1–250 and 250–510)
    - frontend/src/i18n/locales/en/dataset.json (or wherever SourcesTab strings live — grep for `t('...')` calls in SourcesTab.tsx to find the namespace, then read that locale file's relevant section)
    - .planning/backlog/SourcesTab-test-todos.md (verbatim list of 8 items)
  </read_first>
  <behavior>
    Iterate through the 8 backlog items. For each, decide ship-or-migrate:

    **Ship** (default — write a live vitest case) when:
    - SourcesTab today implements the behavior the item describes
    - The test can be expressed with the existing mock-hook harness without new fixtures
    - The assertion is unambiguous (a DOM node exists/doesn't exist, a button is enabled/disabled, a specific link href appears)

    **Migrate** (move to permanent backlog with rationale) when:
    - The behavior in SourcesTab has shifted such that the test author would need to redesign the assertion (e.g., the regenerating banner was replaced with an inline toast → the test concept doesn't translate cleanly)
    - The test would require a new fixture/utility (e.g., a real query-client setup with refetch semantics) that exceeds the closeout budget
    - The behavior is no longer present (e.g., the 2-source floor was removed)

    For each shipped test, write the case using the existing harness pattern:
    ```
    it('<descriptive name from backlog>', () => {
      // override default mocks if needed
      vi.mocked(useVrtSources).mockReturnValue({ data: { sources: <fixture> }, isLoading: false } as ...);
      render(<SourcesTab dataset={mockDataset} />);
      // single clear assertion
      expect(screen.<query>).<matcher>;
    });
    ```

    Each test should be small (≤20 LOC). If a test grows beyond that, consider whether it's actually testing two behaviors and split.

    Expected outcome: 6–8 shipped, 0–2 migrated. If you ship fewer than 6, the audit footprint suggests an under-effort plan — re-read the component and confirm migrations are genuinely justified.
  </behavior>
  <action>
    Step 1 — Read SourcesTab.tsx (510 LOC) in one pass. As you read, note for each of the 8 backlog items: (a) does the behavior exist today? (b) what DOM/ARIA query would assert it? (c) what hook mock override is needed?

    Step 2 — For each item, append a new `it(...)` block inside the existing `describe('SourcesTab', () => { ... })` block, placed AFTER the existing live test at line 134 (so the file stays roughly chronological). Use the existing mock-hook patterns established in `beforeEach`.

    Step 3 — Run the test file in isolation as you go: `cd frontend && npx vitest run src/components/dataset/__tests__/SourcesTab.test.tsx`. Iterate until each new case passes.

    Step 4 — For items you decide to migrate, do NOT add an `it.todo` entry — that would defeat the closeout. Instead, leave the test file with only shipped cases and update the backlog document (next task).

    Step 5 — Final check: `grep -c 'it.todo' frontend/src/components/dataset/__tests__/SourcesTab.test.tsx` must return 0. The closeout assertion is hard zero.

    Step 6 — i18n: if any assertion references a translated string, prefer asserting against the role + accessible name (avoiding brittle string matches), OR import the en locale's value directly via the test-utils i18n setup. Avoid hardcoding English copy that may drift.
  </action>
  <verify>
    <automated>cd frontend &amp;&amp; npx vitest run src/components/dataset/__tests__/SourcesTab.test.tsx &amp;&amp; test "$(grep -c 'it\.todo' frontend/src/components/dataset/__tests__/SourcesTab.test.tsx)" -eq 0</automated>
  </verify>
  <done>
    - 6–8 new live vitest cases in SourcesTab.test.tsx, all passing
    - `grep -c 'it.todo' frontend/src/components/dataset/__tests__/SourcesTab.test.tsx` returns 0
    - Each new test is ≤20 LOC, uses existing harness, asserts against current SourcesTab behavior
  </done>
</task>

<task type="auto">
  <name>Task 2: Update or delete the backlog document with final dispositions</name>
  <files>
    .planning/backlog/SourcesTab-test-todos.md
  </files>
  <read_first>
    - .planning/backlog/SourcesTab-test-todos.md (current file)
    - frontend/src/components/dataset/__tests__/SourcesTab.test.tsx (the just-written file, to capture exact test names for the backlog disposition)
  </read_first>
  <acceptance_criteria>
    - If all 8 items are shipped: delete the backlog file entirely (per the file's own instructions: "When all 8 are landed, delete this file.").
    - If some items are migrated: keep the file with ONLY the migrated items, each rewritten as `- [ ] migrated — <rationale>`. Add a header note: "Remaining items are permanent backlog — no longer tracked as deferred test debt for the SourcesTab milestone."
    - Final file (if kept) MUST NOT have any `- [ ] <item>` entries without a "migrated — rationale" suffix; otherwise the closeout is incomplete.
  </acceptance_criteria>
  <action>
    Choice A (all 8 shipped): Delete `.planning/backlog/SourcesTab-test-todos.md` via the executor's normal delete workflow. Note in the plan SUMMARY that the file was deleted.

    Choice B (some migrated): Rewrite the file to contain only migrated items. Each line becomes:
    ```
    - [ ] migrated — <rationale referencing why the behavior shifted or the budget excluded it>
    ```
    Add a clear header explaining the rewrite, e.g.:
    ```
    # SourcesTab.test.tsx — Permanent Backlog (post-FOLLOWUP-03)

    The 8 items originally listed here were dispositioned in Phase 1048 Plan 03.
    Items below are migrated-to-permanent — no longer tracked as test debt
    against the SourcesTab milestone. Pick up only if the relevant SourcesTab
    behavior changes or a regression surfaces.

    ## Migrated items
    - [ ] migrated — <rationale>
    ```

    Do NOT leave any item without a disposition.
  </action>
  <verify>
    <automated>test ! -f .planning/backlog/SourcesTab-test-todos.md || ! grep -E '^- \[ \] [^m]' .planning/backlog/SourcesTab-test-todos.md</automated>
  </verify>
  <done>
    - File either deleted (Choice A) OR contains only migrated items with rationale (Choice B)
    - No raw `- [ ] <item>` entries without `migrated — <rationale>` prefix
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries
| Boundary | Description |
|----------|-------------|
| n/a (test-only plan) | This plan adds unit tests + updates an internal backlog document; no production code touched |

## STRIDE Threat Register
| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1048-03-01 | n/a | n/a | n/a | No threat surface introduced — test-only plan |
</threat_model>

<verification>
- `cd frontend && npx vitest run src/components/dataset/__tests__/SourcesTab.test.tsx` — all cases pass
- `grep -c 'it.todo' frontend/src/components/dataset/__tests__/SourcesTab.test.tsx` returns 0
- Backlog file deleted OR rewritten with only `migrated — <rationale>` lines
</verification>

<success_criteria>
- FOLLOWUP-03 is complete: 8 backlog items dispositioned (shipped or migrated); net `it.todo` count for SourcesTab is zero; vitest green.
</success_criteria>

<output>
Create `.planning/phases/1048-followups-and-closeout/1048-03-SUMMARY.md` when done. Record:
- Count shipped (with test names)
- Count migrated (with rationales)
- Final disposition of backlog file (deleted or rewritten)
- FOLLOWUP-03 status: complete
</output>
