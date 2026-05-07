/**
 * Phase 279 ADMIN-08 (L-05) regression test: AdminAuditPage page-level
 * guard. Defense-in-depth on top of the backend's
 * require_permission("manage_settings") 403 on /admin/audit-logs/*. The
 * redirect short-circuits a flash of viewer chrome for users who paste
 * /admin/audit directly without admin privileges.
 *
 * The original page-level smoke tests (level-1 heading, breadcrumbs,
 * audit-log-viewer region) are preserved by mounting the page with
 * view_audit granted in the same describe.
 */

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

// LoadingState is internal to the layout module; mock for a deterministic
// data-testid we can assert against without depending on its DOM.
vi.mock('@/components/layout/LoadingState', () => ({
  LoadingState: () => <div data-testid="loading-state">loading</div>,
}));

// usePermissions is controlled per test via mockUsePermissions.
const mockUsePermissions = vi.fn();
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => mockUsePermissions(),
}));

describe('AdminAuditPage', () => {
  beforeEach(() => {
    mockUsePermissions.mockReset();
    // Default: permission granted so the existing smoke tests still apply.
    mockUsePermissions.mockReturnValue({
      can: (cap: string) => cap === 'view_audit',
      isLoading: false,
      permissions: { view_audit: true },
    });
  });

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

describe('AdminAuditPage page guard (ADMIN-08)', () => {
  beforeEach(() => {
    mockUsePermissions.mockReset();
  });

  it('renders LoadingState while permissions are loading', () => {
    mockUsePermissions.mockReturnValue({ can: () => false, isLoading: true, permissions: null });
    render(<AdminAuditPage />);

    expect(screen.getByTestId('loading-state')).toBeInTheDocument();
    expect(screen.queryByTestId('audit-log-viewer')).not.toBeInTheDocument();
  });

  it('redirects (does not render AuditLogViewer) when view_audit permission is missing', () => {
    mockUsePermissions.mockReturnValue({ can: () => false, isLoading: false, permissions: {} });
    render(<AdminAuditPage />);

    // <Navigate to="/admin" replace /> short-circuits before AuditLogViewer mounts.
    // Under the test's MemoryRouter the route resolves to a no-match (no /admin
    // sibling), but AuditLogViewer must NOT have rendered.
    expect(screen.queryByTestId('audit-log-viewer')).not.toBeInTheDocument();
    expect(screen.queryByTestId('loading-state')).not.toBeInTheDocument();
  });

  it('renders AuditLogViewer when view_audit permission is granted', () => {
    mockUsePermissions.mockReturnValue({
      can: (cap: string) => cap === 'view_audit',
      isLoading: false,
      permissions: { view_audit: true },
    });
    render(<AdminAuditPage />);

    expect(screen.getByTestId('audit-log-viewer')).toBeInTheDocument();
    expect(screen.queryByTestId('loading-state')).not.toBeInTheDocument();
  });
});
