/**
 * STACK-04: When SUGGESTED_DATASETS is empty (no-suggestions state), the
 * component must render exactly ONE browse control — the modal-opening
 * "Browse all datasets →" button (aria-label "Browse all datasets in the
 * Add Data modal"). The redundant "Browse catalog →" inner button must be
 * absent.
 */

import { render, screen } from '@/test/test-utils';
import { EmptyStackState } from '../EmptyStackState';

// Override with an empty array to exercise the no-suggestions branch.
// This mock must run before the component import resolves SUGGESTED_DATASETS.
vi.mock('../suggested-datasets', () => ({
  SUGGESTED_DATASETS: [],
}));

vi.mock('@/api/datasets', () => ({
  getDataset: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) =>
      options?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
}));

function defaultProps() {
  return {
    onOpenAddData: vi.fn(),
    onAddDataset: vi.fn(),
  } satisfies React.ComponentProps<typeof EmptyStackState>;
}

describe('EmptyStackState — no-suggestions state (STACK-04)', () => {
  it('renders exactly one browse button when SUGGESTED_DATASETS is empty', () => {
    render(<EmptyStackState {...defaultProps()} />);

    // The one permitted browse control: opens the Add Data modal
    const browseAllBtn = screen.getByRole('button', {
      name: 'Browse all datasets in the Add Data modal',
    });
    expect(browseAllBtn).toBeInTheDocument();

    // The now-removed redundant "Browse catalog" button must be absent
    expect(
      screen.queryByRole('button', { name: 'Browse catalog' }),
    ).not.toBeInTheDocument();

    // Confirm there is exactly one button whose accessible name contains "browse" (case-insensitive)
    const allButtons = screen.getAllByRole('button');
    const browseButtons = allButtons.filter((btn) =>
      /browse/i.test(btn.getAttribute('aria-label') ?? btn.textContent ?? ''),
    );
    expect(browseButtons).toHaveLength(1);
  });

  it('the single browse button calls onOpenAddData with no argument', () => {
    const onOpenAddData = vi.fn();
    render(<EmptyStackState {...defaultProps()} onOpenAddData={onOpenAddData} />);

    const browseBtn = screen.getByRole('button', {
      name: 'Browse all datasets in the Add Data modal',
    });
    browseBtn.click();

    expect(onOpenAddData).toHaveBeenCalledTimes(1);
    const callArgs = onOpenAddData.mock.calls[0];
    expect(callArgs.length === 0 || callArgs[0] === undefined).toBe(true);
  });

  it('does not render the SUGGESTED section or any suggest-card list', () => {
    render(<EmptyStackState {...defaultProps()} />);

    expect(screen.queryByText('SUGGESTED')).not.toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Suggested datasets' })).not.toBeInTheDocument();
  });
});
