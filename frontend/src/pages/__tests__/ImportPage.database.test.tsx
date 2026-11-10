import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { ImportPage } from '../ImportPage';

const mockConnections = vi.fn();
const mockFailed = vi.fn(() => false);
const mockRefetch = vi.fn();
vi.mock('@/components/import/hooks/use-ingest', () => ({
  useDatabaseConnections: () => ({
    data: mockConnections(),
    isError: mockFailed(),
    refetch: mockRefetch,
  }),
}));

vi.mock('@/hooks/use-document-title', () => ({ useDocumentTitle: vi.fn() }));
vi.mock('@/hooks/use-settings-admin', () => ({ useSettingsAdmin: () => false }));
vi.mock('@/components/import/UploadForm', () => ({ UploadForm: () => <div>Upload workflow</div> }));
vi.mock('@/components/import/DatabaseImportForm', () => ({
  DatabaseImportForm: () => <div>Database workflow</div>,
}));

describe('ImportPage database source', () => {
  beforeEach(() => {
    mockFailed.mockReturnValue(false);
    mockRefetch.mockClear();
  });

  it('hides the Database source when no connection is configured', () => {
    mockConnections.mockReturnValue([]);
    render(<ImportPage />);

    expect(screen.queryByRole('button', { name: 'Database' })).not.toBeInTheDocument();
  });

  it('offers the Database source when the account has a connection', async () => {
    mockConnections.mockReturnValue([{ name: 'warehouse', database: 'Warehouse' }]);
    render(<ImportPage />);

    await userEvent.click(screen.getByRole('button', { name: 'Database' }));

    expect(await screen.findByText('Database workflow')).toBeInTheDocument();
  });

  it('says so, with a retry, when the capabilities request failed', async () => {
    mockConnections.mockReturnValue(undefined);
    mockFailed.mockReturnValue(true);
    render(<ImportPage />);

    expect(screen.getByRole('alert')).toHaveTextContent(/Couldn't check which database connections/);
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(mockRefetch).toHaveBeenCalledOnce();
  });

  it('shows no notice when the request succeeded with no connections', () => {
    mockConnections.mockReturnValue([]);
    mockFailed.mockReturnValue(false);
    render(<ImportPage />);

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
