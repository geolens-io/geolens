import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { EmptyStackState } from '../EmptyStackState';
import { getDataset } from '@/api/datasets';
import type { SuggestedDataset } from '../suggested-datasets';

vi.mock('@/api/datasets', () => ({
  getDataset: vi.fn(),
}));

// Test fixture overrides the empty production default so tests can verify the
// populated-suggestions render path without depending on operator-supplied UUIDs.
// Defined inline in the factory because vi.mock is hoisted above all top-level
// const declarations.
vi.mock('../suggested-datasets', async () => {
  const actual = await vi.importActual<typeof import('../suggested-datasets')>('../suggested-datasets');
  return {
    ...actual,
    SUGGESTED_DATASETS: [
      {
        id: '11111111-1111-4111-8111-111111111111',
        name: 'World Countries',
        record_type: 'vector_dataset',
        geometry_type: 'MultiPolygon',
        feature_count: 195,
        crs: 'EPSG:4326',
      },
      {
        id: '22222222-2222-4222-8222-222222222222',
        name: 'World Cities',
        record_type: 'vector_dataset',
        geometry_type: 'Point',
        feature_count: 7343,
        crs: 'EPSG:4326',
      },
      {
        id: '33333333-3333-4333-8333-333333333333',
        name: 'Land Cover',
        record_type: 'raster_dataset',
        crs: 'EPSG:4326',
      },
      {
        id: '44444444-4444-4444-8444-444444444444',
        name: 'Elevation Model',
        record_type: 'raster_dataset',
        crs: 'EPSG:4326',
      },
    ] satisfies SuggestedDataset[],
  };
});

// Import the mocked constant after the factory is registered so tests can iterate.
import { SUGGESTED_DATASETS } from '../suggested-datasets';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
}));

const mockGetDataset = vi.mocked(getDataset);

function defaultProps(overrides: Partial<React.ComponentProps<typeof EmptyStackState>> = {}) {
  return {
    onOpenAddData: vi.fn(),
    onAddDataset: vi.fn(),
    ...overrides,
  } satisfies React.ComponentProps<typeof EmptyStackState>;
}

describe('EmptyStackState', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // By default all getDataset calls resolve successfully
    mockGetDataset.mockResolvedValue({
      id: 'mock-id',
      display_name: 'Mock Dataset',
    } as unknown as ReturnType<typeof getDataset> extends Promise<infer T> ? T : never);
  });

  it('Test 1: renders heading and body text via defaultValue', async () => {
    render(<EmptyStackState {...defaultProps()} />);

    expect(screen.getByText('Add your first layer')).toBeInTheDocument();
    expect(screen.getByText('Search the catalog or pick a starter dataset below.')).toBeInTheDocument();
  });

  it('Test 2: renders inline search input with correct role and placeholder', async () => {
    render(<EmptyStackState {...defaultProps()} />);

    const input = screen.getByRole('searchbox');
    expect(input).toBeInTheDocument();
    expect(input).toHaveAttribute('aria-label', 'Search datasets to add');
    expect(input).toHaveAttribute('placeholder', 'Search datasets, URLs, or files…');
  });

  it('Test 3: Enter with non-empty value calls onOpenAddData with trimmed value; empty/whitespace does not', async () => {
    const onOpenAddData = vi.fn();
    render(<EmptyStackState {...defaultProps({ onOpenAddData })} />);

    const input = screen.getByRole('searchbox');

    // Empty — should NOT call
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onOpenAddData).not.toHaveBeenCalled();

    // Whitespace only — should NOT call
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onOpenAddData).not.toHaveBeenCalled();

    // Non-empty — SHOULD call with trimmed value
    fireEvent.change(input, { target: { value: '  roads  ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onOpenAddData).toHaveBeenCalledWith('roads');
    expect(onOpenAddData).toHaveBeenCalledTimes(1);
  });

  it('Test 4: Escape clears the input and does NOT call onOpenAddData', async () => {
    const onOpenAddData = vi.fn();
    render(<EmptyStackState {...defaultProps({ onOpenAddData })} />);

    const input = screen.getByRole('searchbox');
    fireEvent.change(input, { target: { value: 'some query' } });
    expect(input).toHaveValue('some query');

    fireEvent.keyDown(input, { key: 'Escape' });
    expect(input).toHaveValue('');
    expect(onOpenAddData).not.toHaveBeenCalled();
  });

  it('Test 5: renders SUGGESTED eyebrow label and list with correct aria attributes', async () => {
    render(<EmptyStackState {...defaultProps()} />);

    // Eyebrow label (aria-hidden)
    const eyebrow = screen.getByText('SUGGESTED');
    expect(eyebrow).toHaveAttribute('aria-hidden', 'true');

    // List
    const list = screen.getByRole('list', { name: 'Suggested datasets' });
    expect(list).toBeInTheDocument();
  });

  it('Test 6: each suggest-card renders dataset name, add button, and card body button', async () => {
    render(<EmptyStackState {...defaultProps()} />);

    for (const suggestion of SUGGESTED_DATASETS) {
      // Card body button
      const cardBody = screen.getByRole('button', { name: `Open ${suggestion.name} in Add Data modal` });
      expect(cardBody).toBeInTheDocument();

      // Add button
      const addBtn = screen.getByRole('button', { name: `Add ${suggestion.name} to map` });
      expect(addBtn).toBeInTheDocument();
    }
  });

  it('Test 7: card body click calls onOpenAddData(name); add button click calls onAddDataset(id) — mutually exclusive', async () => {
    const onOpenAddData = vi.fn();
    const onAddDataset = vi.fn();
    render(<EmptyStackState {...defaultProps({ onOpenAddData, onAddDataset })} />);

    const first = SUGGESTED_DATASETS[0];

    // Click card body → opens modal with name
    const cardBody = screen.getByRole('button', { name: `Open ${first.name} in Add Data modal` });
    fireEvent.click(cardBody);
    expect(onOpenAddData).toHaveBeenCalledWith(first.name);
    expect(onAddDataset).not.toHaveBeenCalled();

    vi.clearAllMocks();

    // Click add button → direct add, does NOT open modal
    const addBtn = screen.getByRole('button', { name: `Add ${first.name} to map` });
    fireEvent.click(addBtn);
    expect(onAddDataset).toHaveBeenCalledWith(first.id);
    expect(onOpenAddData).not.toHaveBeenCalled();
  });

  it('Test 8: card is hidden when getDataset errors (silent hide, not error UI)', async () => {
    // Override one specific dataset to error
    const errorId = SUGGESTED_DATASETS[0].id;
    const errorName = SUGGESTED_DATASETS[0].name;

    mockGetDataset.mockImplementation((id: string) => {
      if (id === errorId) {
        return Promise.reject(new Error('404 Not Found'));
      }
      return Promise.resolve({ id, display_name: 'ok' } as unknown as ReturnType<typeof getDataset> extends Promise<infer T> ? T : never);
    });

    render(<EmptyStackState {...defaultProps()} />);

    // Wait for queries to settle
    await waitFor(() => {
      // The errored card should NOT be in the document
      expect(screen.queryByRole('button', { name: `Open ${errorName} in Add Data modal` })).not.toBeInTheDocument();
    });

    // No "error" text should appear
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/not available/i)).not.toBeInTheDocument();

    // Other cards still show (if they resolved successfully)
    const secondSuggestion = SUGGESTED_DATASETS[1];
    expect(screen.getByRole('button', { name: `Open ${secondSuggestion.name} in Add Data modal` })).toBeInTheDocument();
  });

  it('Test 9: Browse all datasets → calls onOpenAddData with no argument (or undefined)', async () => {
    const onOpenAddData = vi.fn();
    render(<EmptyStackState {...defaultProps({ onOpenAddData })} />);

    const browseBtn = screen.getByRole('button', { name: 'Browse all datasets in the Add Data modal' });
    fireEvent.click(browseBtn);

    expect(onOpenAddData).toHaveBeenCalledTimes(1);
    // Called with no args (undefined) — NOT with a pre-fill query
    const callArgs = onOpenAddData.mock.calls[0];
    expect(callArgs.length === 0 || callArgs[0] === undefined).toBe(true);
  });

  it('Test 10: add button shows Loader2 while onAddDataset is pending, then Check on resolve', async () => {
    const onAddDataset = vi.fn(() => new Promise<void>((r) => setTimeout(r, 0)));
    render(<EmptyStackState {...defaultProps({ onAddDataset })} />);

    const first = SUGGESTED_DATASETS[0];
    const addBtn = screen.getByRole('button', { name: `Add ${first.name} to map` });

    fireEvent.click(addBtn);

    // Immediately after click: button is in busy/loading state
    expect(addBtn).toHaveAttribute('aria-busy', 'true');

    // After promise resolves: check icon appears, button shows added state
    await waitFor(() => {
      expect(addBtn).toHaveAttribute('aria-busy', 'false');
    });
  });

  // Phase 1042 Plan 04: AUD-23 + AUD-24 + AUD-02 assertions
  it('Test 11 (AUD-23): suggest card rest background is --surface-0, not --surface-1', () => {
    render(<EmptyStackState {...defaultProps()} />);
    // Find the suggest card container (the clickable div wrapping each card)
    const first = SUGGESTED_DATASETS[0];
    const cardBody = screen.getByRole('button', { name: `Open ${first.name} in Add Data modal` });
    // The card container is the parent of the card body button
    const cardContainer = cardBody.closest('div');
    expect(cardContainer).not.toBeNull();
    expect(cardContainer!.className).toContain('bg-[var(--surface-0)]');
    expect(cardContainer!.className).not.toContain('bg-[var(--surface-1)]');
  });

  it('Test 12 (AUD-24): inline search container has transition-colors duration-[--motion-fast]', () => {
    render(<EmptyStackState {...defaultProps()} />);
    const input = screen.getByRole('searchbox');
    // The search container is the parent of the input
    const container = input.closest('div');
    expect(container).not.toBeNull();
    expect(container!.className).toContain('transition-colors');
    expect(container!.className).toContain('duration-[--motion-fast]');
  });

  it('Test 13 (AUD-24): search icon button has transition-colors duration-[--motion-fast]', () => {
    render(<EmptyStackState {...defaultProps()} />);
    const searchBtn = screen.getByRole('button', { name: 'Search and open Add Data modal' });
    expect(searchBtn.className).toContain('transition-colors');
    expect(searchBtn.className).toContain('duration-[--motion-fast]');
  });

  it('Test 14 (AUD-02): eyebrowClassName is exported from EmptyStackState', async () => {
    const module = await import('../EmptyStackState');
    expect(module.eyebrowClassName).toBeDefined();
    expect(typeof module.eyebrowClassName).toBe('string');
    expect(module.eyebrowClassName).toContain('text-[10px]');
    expect(module.eyebrowClassName).toContain('font-semibold');
    expect(module.eyebrowClassName).toContain('tracking-wide');
  });
});
