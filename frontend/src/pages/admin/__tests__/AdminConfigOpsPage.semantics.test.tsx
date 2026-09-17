import { render, screen } from '@/test/test-utils';
import adminConfigOpsSrc from '../AdminConfigOpsPage.tsx?raw';
import { AdminConfigOpsPage } from '../AdminConfigOpsPage';

const connectivityResult = vi.hoisted(() => ({
  storage: { name: 'storage', status: 'ok', latency_ms: 1, error: null },
  cache: { name: 'cache', status: 'ok', latency_ms: 2, error: null },
  credential_store: {
    name: 'credential_store',
    status: 'error',
    latency_ms: 3,
    error: 'Redis unavailable',
  },
  oidc_providers: {},
}));

vi.mock('@/hooks/use-config-ops', () => ({
  useExportConfig: () => ({ mutate: vi.fn(), isPending: false }),
  useValidateConnectivity: () => ({ mutate: vi.fn(), isPending: false, data: connectivityResult }),
  useDryRunImport: () => ({ mutate: vi.fn(), isPending: false }),
  useImportConfig: () => ({
    mutate: vi.fn(),
    reset: vi.fn(),
    isPending: false,
    isSuccess: false,
    data: undefined,
  }),
}));

describe('AdminConfigOpsPage heading hierarchy', () => {
  it('exposes each top-level operation card as a level-two heading', () => {
    render(<AdminConfigOpsPage />);

    expect(screen.getByRole('heading', { level: 1, name: 'Config Operations' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Export instance configuration' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Validate Connectivity' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Import instance configuration' })).toBeInTheDocument();
  });

  it('uses level-three headings for the conditional import result groups', () => {
    expect(adminConfigOpsSrc).not.toContain('<h4');
    expect(adminConfigOpsSrc.match(/<h3 className="text-sm font-medium">/g)).toHaveLength(2);
  });

  it('shows credential-store failures as a separate connectivity row', () => {
    render(<AdminConfigOpsPage />);

    const row = screen.getByText('Credential store').closest('tr');
    expect(row).not.toBeNull();
    expect(row).toHaveTextContent('Failed');
    expect(row).toHaveTextContent('Redis unavailable');
  });

  it('lists what the export leaves out, with a link to the backup guide', () => {
    render(<AdminConfigOpsPage />);

    const list = screen.getByRole('list', { name: 'What this export leaves out' });
    expect(list).toHaveTextContent('Users and role memberships');
    expect(list).toHaveTextContent('Linked sign-in identities (accounts connected to an OAuth provider)');
    expect(list).toHaveTextContent('Sessions');
    expect(list).toHaveTextContent('Datasets and maps');
    expect(list).toHaveTextContent(
      'Provider secrets and certificates (client secrets and identity-provider signing certificates)',
    );

    const link = screen.getByRole('link', { name: 'backup and restore guide' });
    expect(link).toHaveAttribute('href', 'https://docs.getgeolens.com/guides/admin/backups/');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });
});
