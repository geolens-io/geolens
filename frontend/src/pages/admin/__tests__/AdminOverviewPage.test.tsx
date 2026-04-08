import { render, screen } from '@/test/test-utils';
import { AdminOverviewPage } from '@/pages/admin/AdminOverviewPage';

// Mock StatsOverview since its internals are tested separately and can pull
// in heavy query dependencies.
vi.mock('@/components/admin/StatsOverview', () => ({
  StatsOverview: () => <div data-testid="stats-overview">Stats</div>,
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

describe('AdminOverviewPage', () => {
  it('renders the page header with the overview title', () => {
    render(<AdminOverviewPage />);

    // PageHeader renders a level-1 heading with the title
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toBeInTheDocument();
    expect(heading.textContent).toBeTruthy();
  });

  it('renders the stats overview region', () => {
    render(<AdminOverviewPage />);

    expect(screen.getByTestId('stats-overview')).toBeInTheDocument();
  });

  it('renders the breadcrumbs navigation', () => {
    render(<AdminOverviewPage />);

    // PageHeader exposes breadcrumbs inside a nav landmark
    const nav = screen.getByRole('navigation');
    expect(nav).toBeInTheDocument();
  });
});
