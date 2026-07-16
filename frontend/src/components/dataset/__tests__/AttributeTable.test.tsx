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
import { AttributeTable } from '@/components/dataset/AttributeTable';
import { useDatasetRows } from '@/components/dataset/hooks/use-dataset';
import { useUpdateFeature } from '@/hooks/use-features';

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

  it('preserves cellPadding and existing column visibility logic', () => {
    expect(attributeTableSrc).toMatch(/cellPadding/);
    expect(attributeTableSrc).toMatch(/columnVisibility/);
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
