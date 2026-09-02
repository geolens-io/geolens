import { act, fireEvent, render, screen } from '@/test/test-utils';
import { FilterPanel } from '../FilterPanel';
import { useSearchStore } from '@/stores/search-store';

// Mock useFacets to return known counts
const mockFacets = {
  record_type: { vector_dataset: 10, raster_dataset: 5, vrt_dataset: 0, table: 1, collection: 3 },
};

vi.mock('@/components/search/hooks/use-search', () => ({
  useFacets: () => ({ data: mockFacets, isLoading: false }),
  useCatalogSummary: () => ({ data: undefined, isLoading: false }),
}));

// Mock SavedSearches to avoid auth complexity
vi.mock('../SavedSearches', () => ({
  SaveSearchButton: () => null,
}));

// Mock BboxMapPicker to avoid map loading
vi.mock('../BboxMapPicker', () => ({
  BboxMapPicker: () => <div>mock-map</div>,
}));

describe('FilterPanel', () => {
  afterEach(() => {
    useSearchStore.getState().resetFilters();
  });

  it('renders badge text with counts from useFacets', () => {
    render(<FilterPanel totalResults={18} />);

    // Desktop toggle items should show counts (All includes table records too).
    expect(screen.getByText(/All.*\(16\)/)).toBeInTheDocument();
    expect(screen.getByText(/Vector.*\(10\)/)).toBeInTheDocument();
    expect(screen.getByText(/Raster.*\(5\)/)).toBeInTheDocument();
    expect(screen.getByText(/Table.*\(1\)/)).toBeInTheDocument();
  });

  it('disables badges with count of 0', () => {
    render(<FilterPanel totalResults={18} />);

    // Virtual Raster has count 0, its toggle button should be disabled
    const vrtButtons = screen.getAllByRole('radio').filter(
      (el) => el.textContent?.includes('Virtual Raster') && el.textContent?.includes('(0)'),
    );
    expect(vrtButtons.length).toBeGreaterThan(0);
    expect(vrtButtons[0]).toBeDisabled();
  });

  it('does not show collection as a record type toggle', () => {
    render(<FilterPanel totalResults={15} />);

    // Collections should not appear as a toggle group item
    const radios = screen.getAllByRole('radio');
    const collectionRadio = radios.find((el) => el.textContent?.includes('Collections'));
    expect(collectionRadio).toBeUndefined();
  });

  it('does not render secondary filter row when no record type is selected', () => {
    render(<FilterPanel totalResults={18} />);

    expect(screen.queryByTestId('secondary-filter-row')).not.toBeInTheDocument();
  });

  it('does not render secondary filter row for raster type when no org/crs available', () => {
    useSearchStore.getState().setFilter('record_type', 'raster_dataset');
    render(<FilterPanel totalResults={5} />);

    expect(screen.queryByTestId('secondary-filter-row')).not.toBeInTheDocument();
  });

  it('does not render secondary filter row for table type when no table-specific secondary filters are available', () => {
    useSearchStore.getState().setFilter('record_type', 'table');
    render(<FilterPanel totalResults={1} />);

    expect(screen.queryByTestId('secondary-filter-row')).not.toBeInTheDocument();
  });

  it('renders secondary filter row with Vector filters label when vector type selected', () => {
    useSearchStore.getState().setFilter('record_type', 'vector_dataset');
    render(<FilterPanel totalResults={10} />);

    const secondaryRow = screen.getByTestId('secondary-filter-row');
    expect(secondaryRow).toBeInTheDocument();
    expect(secondaryRow).toHaveTextContent(/Vector.*filters/);
  });
});

// fix(#1761 review round 4): the uncommitted date-range draft
// (localDateFrom/localDateTo) used to survive an identity change, so
// clicking the still-open popover's Apply afterward repopulated the
// (now cleared) store and URL with the previous identity's typed dates.
describe('FilterPanel identity reset (fix #1761 review round 4)', () => {
  afterEach(() => {
    useSearchStore.getState().resetFilters();
  });

  // Radix Popover portals its content to document.body, outside render()'s
  // own container, so query the document rather than the container.
  function getDateInputs() {
    return Array.from(document.querySelectorAll<HTMLInputElement>('input[type="date"]'));
  }

  it('clears an uncommitted date draft and closes the popover when identity changes', () => {
    render(<FilterPanel totalResults={10} showMobile={false} />);

    fireEvent.click(screen.getByRole('button', { name: /Date Added/i }));
    const [fromInput] = getDateInputs();
    fireEvent.change(fromInput, { target: { value: '2024-01-01' } });
    expect(getDateInputs()[0]).toHaveValue('2024-01-01');
    // Still uncommitted: date_from in the store is untouched.
    expect(useSearchStore.getState().date_from).toBe('');

    // Identity changes (the auth choke point's identity-change branch)
    // WITHOUT the user clicking Apply.
    act(() => {
      useSearchStore.getState().clearIdentityScopedFilters();
    });

    // Popover closed: Apply is no longer reachable with the stale draft.
    expect(screen.queryByRole('button', { name: /Apply/i })).not.toBeInTheDocument();

    // Reopening shows the cleared value, not the stale draft.
    fireEvent.click(screen.getByRole('button', { name: /Date Added/i }));
    expect(getDateInputs()[0]).toHaveValue('');
  });

  // fix(#1761 review round 4, sweep): spatialPanelOpen was originally
  // classified as a kept presentation preference, but it gates whether
  // SpatialFilterPanel is mounted, and that component holds its own
  // uncommitted pendingBbox/predicate draft — the same class of bug as the
  // date draft above, just reached through onApply instead of directly.
  // Left open across an identity change, Apply would write the previous
  // identity's drawn area into the just-cleared store.
  it('closes the spatial filter panel on identity change', () => {
    render(<FilterPanel totalResults={10} showMobile={false} />);

    fireEvent.click(screen.getByRole('button', { name: /^Location$/i }));
    expect(useSearchStore.getState().spatialPanelOpen).toBe(true);

    act(() => {
      useSearchStore.getState().clearIdentityScopedFilters();
    });

    expect(useSearchStore.getState().spatialPanelOpen).toBe(false);
  });
});
