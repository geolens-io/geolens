import { act, fireEvent, render, screen } from '@/test/test-utils';
import { FilterSheet } from '../FilterSheet';
import { useSearchStore } from '@/stores/search-store';

vi.mock('@/components/search/hooks/use-search', () => ({
  useFacets: () => ({ data: { record_type: {} }, isLoading: false }),
  useCatalogSummary: () => ({ data: undefined, isLoading: false }),
}));

vi.mock('../SavedSearches', () => ({
  SaveSearchButton: () => null,
}));

vi.mock('../BboxMapPicker', () => ({
  BboxMapPicker: () => <div>mock-map</div>,
}));

// fix(#1761 review round 4): same class as FilterPanel — the uncommitted
// date-range draft (localDateFrom/localDateTo) used to survive an identity
// change, so clicking Apply afterward repopulated the (now cleared) store
// with the previous identity's typed dates. The whole sheet (and its
// nested bbox popover) should also close.
describe('FilterSheet identity reset (fix #1761 review round 4)', () => {
  afterEach(() => {
    useSearchStore.getState().resetFilters();
  });

  // The "Date Added" draft inputs render before the (unrelated,
  // directly-committed) Temporal Extent inputs, so they are always the
  // first two type="date" inputs once the sheet is open.
  function getDateDraftInputs() {
    return Array.from(document.querySelectorAll<HTMLInputElement>('input[type="date"]')).slice(0, 2);
  }

  it('clears an uncommitted date draft and closes the sheet when identity changes', () => {
    render(<FilterSheet totalResults={10} />);

    fireEvent.click(screen.getByRole('button', { name: /Filters/i }));
    const [fromInput] = getDateDraftInputs();
    fireEvent.change(fromInput, { target: { value: '2024-01-01' } });
    expect(getDateDraftInputs()[0]).toHaveValue('2024-01-01');
    expect(useSearchStore.getState().date_from).toBe('');

    // Identity changes WITHOUT the user clicking Apply.
    act(() => {
      useSearchStore.getState().clearIdentityScopedFilters();
    });

    // The whole sheet closed — its contents (including the stale draft)
    // are no longer reachable.
    expect(screen.queryByRole('button', { name: /^Apply$/i })).not.toBeInTheDocument();

    // Reopening shows the cleared value, not the stale draft.
    fireEvent.click(screen.getByRole('button', { name: /Filters/i }));
    expect(getDateDraftInputs()[0]).toHaveValue('');
  });
});

// fix(#1778): the sheet's date-range and temporal-extent sections each
// paired a bare <label> (no htmlFor) with a sibling <Input>, extracted
// verbatim from FilterPanel's same bug — so all four date fields in the
// mobile sheet announced as unnamed. The sheet is closed at mount, so the
// axe gate structurally cannot reach it.
describe('FilterSheet date field accessible names (#1778)', () => {
  afterEach(() => {
    useSearchStore.getState().resetFilters();
  });

  it('names all four "From"/"To" date inputs once the sheet is open', () => {
    render(<FilterSheet totalResults={10} />);

    fireEvent.click(screen.getByRole('button', { name: /Filters/i }));

    expect(screen.getAllByLabelText('From')).toHaveLength(2);
    expect(screen.getAllByLabelText('To')).toHaveLength(2);
  });
});
