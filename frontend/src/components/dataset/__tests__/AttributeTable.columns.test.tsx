/**
 * The `columns` prop orders the table, titles its headers and labels coded
 * values; its hidden entries wait in the Columns menu and unlisted columns
 * never show. A selected row is scrolled clear of the sticky header. The
 * `display` flags drop the types and filters and announce the count.
 * `useVirtualizer` is stubbed because jsdom computes no layout (see
 * AttributeTable.test.tsx).
 */
import { afterEach, describe, it, expect, vi, beforeEach } from 'vitest';
import userEvent from '@testing-library/user-event';
import { render, screen, within } from '@/test/test-utils';
import { AttributeTable } from '@/components/dataset/AttributeTable';
import { useDatasetRows } from '@/components/dataset/hooks/use-dataset';
import { useAuthStore } from '@/stores/auth-store';

vi.mock('@/components/dataset/hooks/use-dataset', () => ({
  useDatasetRows: vi.fn(),
}));
vi.mock('@/hooks/use-debounce', () => ({
  useDebouncedValue: (value: unknown) => value,
}));
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count, estimateSize }: { count: number; estimateSize: () => number }) => ({
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({
        index,
        key: index,
        start: index * estimateSize(),
        size: estimateSize(),
      })),
    getTotalSize: () => count * estimateSize(),
    measure: () => {},
  }),
}));

const COLUMNS = [
  { name: 'size', title: 'Lot size' },
  { name: 'status', valueLabels: { '1': 'Active' } },
  { name: 'owner', hidden: true },
];

function headerNames() {
  // The first row is the titles; the second holds the filter inputs.
  return within(screen.getAllByRole('row')[0])
    .getAllByRole('columnheader')
    .map((header) => header.textContent ?? '');
}

describe('AttributeTable columns prop', () => {
  beforeEach(() => {
    useAuthStore.setState({ sessionEpoch: 0, user: null });
    vi.mocked(useDatasetRows).mockReturnValue({
      data: {
        columns: [
          { name: 'gid', type: 'integer' },
          { name: 'status', type: 'integer' },
          { name: 'owner', type: 'text' },
          { name: 'size', type: 'integer' },
        ],
        rows: [
          { gid: 1, status: 1, owner: 'x', size: 10 },
          { gid: 2, status: 7, owner: 'y', size: 20 },
        ],
        next_cursor: null,
        approximate_total: 2,
      },
      isLoading: false,
      isFetching: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetRows>);
  });

  it('shows only the listed columns, in order, under their titles', () => {
    render(<AttributeTable datasetId="ds" columns={COLUMNS} />);

    const names = headerNames();
    expect(names).toHaveLength(2);
    expect(names[0]).toContain('Lot size');
    expect(names[1]).toContain('status');
    expect(screen.queryByText('owner')).not.toBeInTheDocument();
  });

  it('never offers a column the list leaves out', async () => {
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds" columns={COLUMNS} />);

    await user.click(screen.getByRole('button', { name: /columns/i }));
    expect(screen.getByRole('menuitemcheckbox', { name: 'owner' })).not.toBeChecked();
    expect(screen.queryByRole('menuitemcheckbox', { name: 'gid' })).not.toBeInTheDocument();
  });

  it('drops the SQL types and the filter row for readers, and announces the count', async () => {
    render(
      <AttributeTable
        datasetId="ds"
        columns={COLUMNS}
        display={{ hideColumnTypes: true, hideColumnFilters: true, announceCount: true }}
      />,
    );

    expect(headerNames()).toEqual(['Lot size', 'status']);
    expect(screen.getAllByRole('row')[1]).not.toHaveTextContent(/filter/i);
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(await screen.findByText(/of ~?2 rows/, { selector: '[aria-live="polite"]' }, { timeout: 2000 })).toBeInTheDocument();
  });

  it('labels coded values from the column entry', () => {
    render(<AttributeTable datasetId="ds" columns={COLUMNS} />);

    expect(screen.getByRole('button', { name: 'Active' })).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
  });

  it('adds a hidden column from the Columns menu in its listed place', async () => {
    const user = userEvent.setup();
    render(<AttributeTable datasetId="ds" columns={COLUMNS} />);

    await user.click(screen.getByRole('button', { name: /columns/i }));
    expect(screen.getByRole('menuitemcheckbox', { name: 'Lot size' })).toBeChecked();
    await user.click(screen.getByRole('menuitemcheckbox', { name: 'owner' }));
    await user.keyboard('{Escape}');

    const names = headerNames();
    expect(names).toHaveLength(3);
    expect(names[2]).toContain('owner');
  });

  it('shows every column as returned without the prop', () => {
    render(<AttributeTable datasetId="ds" />);

    expect(headerNames()).toHaveLength(4);
  });
});

describe('AttributeTable selectedGid', () => {
  const ROWS = Array.from({ length: 30 }, (_, index) => ({ gid: index + 1 }));

  beforeEach(() => {
    useAuthStore.setState({ sessionEpoch: 0, user: null });
    vi.mocked(useDatasetRows).mockReturnValue({
      data: {
        columns: [{ name: 'gid', type: 'integer' }],
        rows: ROWS,
        next_cursor: null,
        approximate_total: ROWS.length,
      },
      isLoading: false,
      isFetching: false,
      isError: false,
    } as unknown as ReturnType<typeof useDatasetRows>);
  });

  // A 200px scroller under a 60px sticky header, with 28px compact rows.
  function stubLayout() {
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function clientHeight(this: HTMLElement) {
      return this.getAttribute('role') === 'region' ? 200 : 0;
    });
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function offsetHeight(this: HTMLElement) {
      return this.tagName === 'THEAD' ? 60 : 0;
    });
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('scrolls a selected row fully clear of the sticky header and the bottom edge', () => {
    stubLayout();
    const { rerender } = render(<AttributeTable datasetId="ds" compact selectedGid={null} />);
    const scroller = screen.getByRole('region');
    expect(scroller.scrollTop).toBe(0);

    // Row 20 (index 19) spans 592-620; its bottom meets the visible bottom.
    rerender(<AttributeTable datasetId="ds" compact selectedGid={20} />);
    expect(scroller.scrollTop).toBe(420);

    // Row 2 (index 1) spans 88-116; its top settles right under the header.
    rerender(<AttributeTable datasetId="ds" compact selectedGid={2} />);
    expect(scroller.scrollTop).toBe(28);
  });

  it('leaves the scroll alone for a gid that is off the page', () => {
    stubLayout();
    render(<AttributeTable datasetId="ds" compact selectedGid={99} />);
    expect(screen.getByRole('region').scrollTop).toBe(0);
  });
});
