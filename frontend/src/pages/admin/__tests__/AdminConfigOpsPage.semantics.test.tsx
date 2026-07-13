import { render, screen } from '@/test/test-utils';
import adminConfigOpsSrc from '../AdminConfigOpsPage.tsx?raw';
import { AdminConfigOpsPage } from '../AdminConfigOpsPage';

vi.mock('@/hooks/use-config-ops', () => ({
  useExportConfig: () => ({ mutate: vi.fn(), isPending: false }),
  useValidateConnectivity: () => ({ mutate: vi.fn(), isPending: false, data: undefined }),
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
    expect(screen.getByRole('heading', { level: 2, name: 'Export Configuration' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Validate Connectivity' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Import Configuration' })).toBeInTheDocument();
  });

  it('uses level-three headings for the conditional import result groups', () => {
    expect(adminConfigOpsSrc).not.toContain('<h4');
    expect(adminConfigOpsSrc.match(/<h3 className="text-sm font-medium">/g)).toHaveLength(2);
  });
});
