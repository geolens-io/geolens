/**
 * Regression tests for RegisterForm empty-state branching (IMPORT-05).
 *
 * Two variants:
 *   1. allRegistered — tables=[], datasetCountHint > 0  → success framing
 *   2. noTables      — tables=[], datasetCountHint = 0  → absence framing
 *   3. nonEmpty      — tables=[…]                       → normal list render
 */
import { render, screen } from '@/test/test-utils';
import { RegisterForm } from '../RegisterForm';

// ── Mock the entire use-ingest module ────────────────────────────────────────
// Individual tests override these via mockImplementation on the hoisted refs.
const mockUseDiscoverTables = vi.fn();
const mockUseDatasetCountHint = vi.fn();
const mockUseBulkRegister = vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false }));

vi.mock('@/components/import/hooks/use-ingest', () => ({
  useDiscoverTables: () => mockUseDiscoverTables(),
  useDatasetCountHint: (_enabled: boolean) => mockUseDatasetCountHint(),
  useBulkRegister: () => mockUseBulkRegister(),
}));

// ── Stub i18n — return the key so assertions are key-based ──────────────────
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

// ── Stub router hooks used inside RegisterForm ───────────────────────────────
vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    Link: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) => (
      <a {...props}>{children}</a>
    ),
  };
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe('RegisterForm empty state', () => {
  test('shows all-registered success variant when tables=[] and datasetCount > 0', () => {
    mockUseDiscoverTables.mockReturnValue({
      data: { tables: [] },
      isLoading: false,
      error: null,
    });
    mockUseDatasetCountHint.mockReturnValue({ data: 5 });

    render(<RegisterForm />);

    expect(screen.getByText('register.emptyStateAllRegistered.title')).toBeInTheDocument();
    expect(screen.queryByText('register.emptyState')).not.toBeInTheDocument();
    expect(screen.queryByText('register.emptyStateNoTables.title')).not.toBeInTheDocument();
  });

  test('shows no-tables absence variant when tables=[] and datasetCount = 0', () => {
    mockUseDiscoverTables.mockReturnValue({
      data: { tables: [] },
      isLoading: false,
      error: null,
    });
    mockUseDatasetCountHint.mockReturnValue({ data: 0 });

    render(<RegisterForm />);

    expect(screen.getByText('register.emptyStateNoTables.title')).toBeInTheDocument();
    expect(screen.queryByText('register.emptyState')).not.toBeInTheDocument();
    expect(screen.queryByText('register.emptyStateAllRegistered.title')).not.toBeInTheDocument();
  });

  test('renders table list (not empty state) when tables are present', () => {
    mockUseDiscoverTables.mockReturnValue({
      data: {
        tables: [
          {
            table_name: 'parcels',
            geometry_type: 'Polygon',
            srid: 4326,
            estimated_rows: 1000,
          },
        ],
      },
      isLoading: false,
      error: null,
    });
    // hint not needed in non-empty branch — return a safe default
    mockUseDatasetCountHint.mockReturnValue({ data: undefined });

    render(<RegisterForm />);

    expect(screen.getByText('parcels')).toBeInTheDocument();
    expect(screen.queryByText('register.emptyStateAllRegistered.title')).not.toBeInTheDocument();
    expect(screen.queryByText('register.emptyStateNoTables.title')).not.toBeInTheDocument();
  });
});
