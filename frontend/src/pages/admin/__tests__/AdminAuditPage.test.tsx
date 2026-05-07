import { render, screen } from '@/test/test-utils';
import { AdminAuditPage } from '@/pages/admin/AdminAuditPage';

// AuditLogViewer fetches paginated audit events through TanStack Query;
// mock so the page-level test stays scoped to route composition.
vi.mock('@/components/admin/AuditLogViewer', () => ({
  AuditLogViewer: () => <div data-testid="audit-log-viewer">Audit log viewer region</div>,
}));

vi.mock('@/hooks/use-document-title', () => ({
  useDocumentTitle: vi.fn(),
}));

describe('AdminAuditPage', () => {
  it('renders the level-1 page heading', () => {
    render(<AdminAuditPage />);

    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toBeInTheDocument();
    expect(heading.textContent).toBeTruthy();
  });

  it('renders the breadcrumbs navigation landmark', () => {
    render(<AdminAuditPage />);

    expect(screen.getByRole('navigation')).toBeInTheDocument();
  });

  it('renders the audit log viewer region', () => {
    render(<AdminAuditPage />);

    expect(screen.getByTestId('audit-log-viewer')).toBeInTheDocument();
  });
});
