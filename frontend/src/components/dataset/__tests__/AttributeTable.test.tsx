/**
 * PERF-07 (Phase 274): regression-lock that AttributeTable uses
 * @tanstack/react-virtual for row windowing and that the virtualizer is wired
 * against the parent scroll element.
 *
 * Uses Vite's `?raw` query suffix to load the source as a string at build time
 * — no node fs needed, runs purely in the browser test environment. Same
 * pattern used by `DatasetMap.lazy.test.tsx` for PERF-06.
 *
 * jsdom does not compute layout (getBoundingClientRect returns zeros), so a
 * full DOM render test cannot meaningfully assert that virtualization renders
 * the correct subset of rows. Instead, this suite uses static-source
 * assertions to lock the wiring contract: the imports, the parentRef, the
 * useVirtualizer call, and the key shape of the body render path.
 * Render-correctness is exercised manually + via Playwright in the existing
 * dataset E2E spec.
 *
 * GLUX-002 (Phase 1248): accessible-name regression gate — a separate DOM
 * render suite below asserts that filter inputs are queryable by accessible
 * name. The filter row lives in <thead> (not virtualized), so jsdom can render
 * and interrogate it without layout computation.
 */
import { describe, it, expect } from 'vitest';
import attributeTableSrc from '@/components/dataset/AttributeTable.tsx?raw';

// ── GLUX-002 DOM render gate ─────────────────────────────────────────────────
import { render, screen } from '@/test/test-utils';
import { vi } from 'vitest';
import { AttributeTable, features } from '@/components/dataset/AttributeTable';
import { useDatasetRows } from '@/components/dataset/hooks/use-dataset';
import { useUpdateFeature } from '@/hooks/use-features';

// ── #1407 sortFn auto-detection regression lock ─────────────────────────────
import { renderHook } from '@testing-library/react';
import { useTable, type ColumnDef } from '@tanstack/react-table';

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetRows: vi.fn(),
}));
vi.mock('@/hooks/use-features', () => ({
  useUpdateFeature: vi.fn(),
}));
// Pass debounced value through so filter state changes propagate immediately
vi.mock('@/hooks/use-debounce', () => ({
  useDebouncedValue: (value: unknown) => value,
}));

describe('GLUX-002: AttributeTable filter input accessible name', () => {
  beforeEach(() => {
    vi.mocked(useDatasetRows).mockReturnValue({
      data: {
        columns: [{ name: 'title', type: 'text' }],
        rows: [{ gid: 1, title: 'Test Row' }],
        next_cursor: null,
        approximate_total: 1,
      },
      isLoading: false,
      isFetching: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetRows>);

    vi.mocked(useUpdateFeature).mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useUpdateFeature>);
  });

  it('filter input in the header is queryable by its accessible name', () => {
    render(<AttributeTable datasetId="test-ds" />);
    // The filter row is in <thead> (not virtualized) and each Input carries
    // aria-label="${t('attributes.filter')} ${columnId}". Querying by role
    // and accessible name is the regression gate — removing the aria-label
    // breaks this assertion.
    const filterInput = screen.getByRole('textbox', { name: /filter/i });
    expect(filterInput).toBeInTheDocument();
  });
});

describe('PERF-07: AttributeTable virtualization wiring', () => {
  it('imports useVirtualizer from @tanstack/react-virtual', () => {
    expect(attributeTableSrc).toMatch(
      /import\s*\{[^}]*\buseVirtualizer\b[^}]*\}\s*from\s*['"]@tanstack\/react-virtual['"]/,
    );
  });

  it('declares a parentRef wired into the scroll container', () => {
    expect(attributeTableSrc).toMatch(/parentRef\s*=\s*useRef/);
    expect(attributeTableSrc).toMatch(/ref=\{parentRef\}/);
  });

  it('calls useVirtualizer with getScrollElement returning parentRef.current', () => {
    expect(attributeTableSrc).toMatch(/getScrollElement:[^,}]*parentRef/);
  });

  it('renders the body via getVirtualItems()', () => {
    expect(attributeTableSrc).toMatch(/virtualizer\.getVirtualItems\(\)/);
  });

  it('uses getTotalSize for the scrollable height', () => {
    expect(attributeTableSrc).toMatch(/virtualizer\.getTotalSize\(\)/);
  });

  it('preserves per-density cell classes and existing column visibility logic', () => {
    expect(attributeTableSrc).toMatch(/cellClass/);
    expect(attributeTableSrc).toMatch(/columnVisibility/);
  });

  // fix(#820): dynamic measurement (measureElement) fed back synchronously
  // (measure→layout→re-render) when a Chrome AX tree was attached, freezing
  // the page in an infinite render loop. Rows are fixed-height; reintroducing
  // measureElement reintroduces the freeze. Live coverage: e2e/attribute-table-ax.spec.ts.
  it('does not use measureElement / dynamic row measurement', () => {
    expect(attributeTableSrc).not.toContain('measureElement');
  });

  // fix(#820): with measurement gone, the virtualizer's row size and the
  // rendered row height must agree by construction. The row height is derived
  // from the density mode (44px default / 28px compact, measured in Chromium)
  // and enforced on the cells via matching height classes (h-11 / h-7, py-0).
  it('derives the virtualizer row size from the density mode and enforces it on the cells', () => {
    expect(attributeTableSrc).toMatch(/rowHeight = compact \? 28 : 44/);
    expect(attributeTableSrc).toMatch(/estimateSize: \(\) => rowHeight/);
    expect(attributeTableSrc).toMatch(/compact \? 'h-7 py-0 text-xs' : 'h-11 py-0'/);
  });

  // fix(#851): virtual-core does not invalidate its measurement cache when
  // estimateSize changes, so a density toggle must explicitly call
  // virtualizer.measure() or totals/offsets keep the old row height.
  it('resets cached row sizes when the density mode changes', () => {
    expect(attributeTableSrc).toMatch(/virtualizer\.measure\(\)/);
  });
});

// ── fix(#458 E-35/E-39/E-51) source contracts ────────────────────────────────
// The body rows are virtualized, and jsdom computes no layout, so the cell
// editor can't be rendered here (same constraint as PERF-07 above). Lock the
// contracts against the source instead; the live flow is covered by
// e2e/feature-editing.spec.ts.
describe('AttributeTable editing contracts (E-35/E-39/E-51)', () => {
  it('E-35: an unchanged cell value commits as a cancel, not a PATCH', () => {
    // commit() guards on value === initialValue and routes to onCancel —
    // removing the guard reintroduces no-op writes (tile purge + audit noise).
    expect(attributeTableSrc).toMatch(
      /if \(value === initialValue\) \{\s*onCancel\(\);\s*return;\s*\}/,
    );
    // blur goes through commit, never straight to onSave
    expect(attributeTableSrc).toContain('onBlur={commit}');
    expect(attributeTableSrc).not.toContain('onBlur={() => onSave(value)}');
  });

  it('E-39: the cell editor is named and carries invalid-state wiring', () => {
    expect(attributeTableSrc).toContain('aria-label={label}');
    expect(attributeTableSrc).toContain('aria-invalid={error ? true : undefined}');
    expect(attributeTableSrc).toContain('aria-describedby={error ? errorId : undefined}');
    expect(attributeTableSrc).toContain("t('attributes.cellEditorLabel'");
  });

  it('E-51: an open cell edit closes when the row set changes', () => {
    expect(attributeTableSrc).toMatch(
      /setEditingCell\(null\);\s*setEditError\(null\);\s*\}, \[cursor, activeFilters, pageSize\]\)/,
    );
  });
});

// ── #1407 sortFn auto-detection regression lock ──────────────────────────────
// AttributeTable builds its columns dynamically from the dataset's Postgres
// column list and never sets a per-column sortFn, so sorting depends on
// react-table v9's runtime auto-detection (column_getAutoSortFn, which samples
// each column's first 10 values) resolving to a sortFn *name* that is actually
// registered in the `features` object exported by AttributeTable.tsx. A gap
// there doesn't fail typecheck or build — a column with an unregistered
// auto-detected name silently falls back to the `basic` comparator (or a
// dev-only console.warn), which is exactly the kind of regression the v8→v9
// migration (GH-1407) needed live verification for. This exercises the real
// useTable()/features config end-to-end against synthetic rows shaped like
// the Postgres column families the table actually renders — no mocking of
// react-table itself.
describe('#1407: react-table v9 sortFn auto-detection for dynamic columns', () => {
  function useSortedColumn(data: Array<{ value: unknown }>) {
    const columns: ColumnDef<typeof features, { value: unknown }>[] = [
      { accessorKey: 'value', header: 'value' },
    ];
    return useTable(
      {
        features,
        data,
        columns,
        state: { sorting: [{ id: 'value', desc: false }], columnVisibility: {} },
        onSortingChange: () => {},
        onColumnVisibilityChange: () => {},
      },
      (state) => state,
    );
  }

  it('sorts a numeric column ascending via the auto-detected basic sortFn', () => {
    const { result } = renderHook(() =>
      useSortedColumn([{ value: 30 }, { value: 5 }, { value: 100 }]),
    );
    const sorted = result.current.getSortedRowModel().rows.map((r) => r.original.value);
    expect(sorted).toEqual([5, 30, 100]);
  });

  it('sorts a text column via the auto-detected text sortFn', () => {
    const { result } = renderHook(() =>
      useSortedColumn([{ value: 'cherry' }, { value: 'Apple' }, { value: 'banana' }]),
    );
    const sorted = result.current.getSortedRowModel().rows.map((r) => r.original.value);
    expect(sorted).toEqual(['Apple', 'banana', 'cherry']);
  });

  // The API serializes timestamp columns as ISO-8601 strings, never real Date
  // instances (JSON has no Date type), so column_getAutoSortFn's `[object
  // Date]` check never matches them — they auto-detect as 'alphanumeric', not
  // 'datetime'. That's unchanged from v8 (same heuristic). What matters here
  // is that zero-padded same-format ISO strings still sort chronologically
  // under the alphanumeric comparator, and that 'alphanumeric' is registered.
  it('sorts an ISO-timestamp-string column chronologically via the auto-detected alphanumeric sortFn', () => {
    const { result } = renderHook(() =>
      useSortedColumn([
        { value: '2026-03-01T00:00:00' },
        { value: '2024-01-01T00:00:00' },
        { value: '2025-06-15T00:00:00' },
      ]),
    );
    const sorted = result.current.getSortedRowModel().rows.map((r) => r.original.value);
    expect(sorted).toEqual([
      '2024-01-01T00:00:00',
      '2025-06-15T00:00:00',
      '2026-03-01T00:00:00',
    ]);
  });
});
