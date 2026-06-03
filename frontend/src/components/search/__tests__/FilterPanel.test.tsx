import { render, screen } from '@/test/test-utils';
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
