import { render, screen, waitFor } from '@/test/test-utils';
import { render as renderBare } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import userEvent from '@testing-library/user-event';
import { ApiError } from '@/api/client';
import { translateApiErrorDetail } from '@/lib/error-map';
import { toast } from 'sonner';
import { useAuthStore } from '@/stores/auth-store';
import { clearDatabaseImport } from '@/api/database-import-session';
import { DatabaseImportForm } from '../DatabaseImportForm';
import type { DatabaseTable } from '@/types/api';

const mockCapabilities = vi.fn();
const mockListTables = vi.fn();
const mockStartImport = vi.fn();
const mockJobStatus = vi.fn();

vi.mock('@/api/ingest', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/ingest')>()),
  getCapabilities: () => mockCapabilities(),
  listDatabaseTables: (...args: unknown[]) => mockListTables(...args),
  startDatabaseImport: (...args: unknown[]) => mockStartImport(...args),
  getJobStatus: (...args: unknown[]) => mockJobStatus(...args),
}));

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock('../JobProgress', () => ({
  JobProgress: ({ jobId }: { jobId: string }) => <div>Tracking {jobId}</div>,
}));

function table(overrides: Partial<DatabaseTable> = {}): DatabaseTable {
  return {
    schema_name: 'gis',
    table_name: 'parcels',
    object_type: 'table',
    geometry_column: 'shape',
    column_type: 'geometry',
    srid: 4326,
    importable: true,
    ...overrides,
  };
}

function listing(tables: DatabaseTable[], truncated = false) {
  return { connection: 'warehouse', database: 'Warehouse', tables, limit: 500, truncated };
}

function withConnections(...names: string[]) {
  mockCapabilities.mockResolvedValue({
    me: {
      username: 'a',
      permissions: [],
      key: null,
      remaining_dataset_quota: null,
      database_connections: names.map((name) => ({ name, database: `${name}-db` })),
    },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  clearDatabaseImport();
  mockJobStatus.mockResolvedValue({ id: 'job-9', status: 'running' });
  useAuthStore.setState({ token: 'token', user: null });
  withConnections('warehouse');
});

async function openReview(user: ReturnType<typeof userEvent.setup>, row: string) {
  await user.click(await screen.findByRole('radio', { name: new RegExp(row) }));
  await user.click(screen.getByRole('button', { name: 'Continue' }));
}

describe('DatabaseImportForm', () => {
  it('lists the tables of the only connection with kind and SRID', async () => {
    mockListTables.mockResolvedValue(
      listing([table(), table({ table_name: 'v_zones', object_type: 'view', srid: null })]),
    );
    render(<DatabaseImportForm />);

    expect(await screen.findByRole('radio', { name: /gis\.parcels/ })).toBeInTheDocument();
    expect(mockListTables).toHaveBeenCalledWith('warehouse');
    expect(screen.getByText('EPSG:4326')).toBeInTheDocument();
    expect(screen.getByText('No SRID')).toBeInTheDocument();
    expect(screen.getByText('View')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
  });

  it('asks which connection to list when there are several', async () => {
    withConnections('warehouse', 'archive');
    mockListTables.mockResolvedValue(listing([table()]));
    const user = userEvent.setup();
    render(<DatabaseImportForm />);

    await user.click(await screen.findByRole('radio', { name: /archive/ }));

    await waitFor(() => expect(mockListTables).toHaveBeenCalledWith('archive'));
    expect(mockListTables).not.toHaveBeenCalledWith('warehouse');
  });

  it('notes a truncated listing', async () => {
    mockListTables.mockResolvedValue(listing([table()], true));
    render(<DatabaseImportForm />);

    expect(await screen.findByText(/Only the first 500 spatial columns/)).toBeInTheDocument();
  });

  it('shows the listing failure text', async () => {
    mockListTables.mockRejectedValue(new ApiError('Could not reach the connection "warehouse".', 502));
    render(<DatabaseImportForm />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the connection "warehouse".');
  });

  it('imports a table that has an SRID without asking for one', async () => {
    mockListTables.mockResolvedValue(listing([table()]));
    mockStartImport.mockResolvedValue({ job_id: 'job-9', status: 'pending', message: 'queued' });
    const user = userEvent.setup();
    render(<DatabaseImportForm />);

    await openReview(user, 'gis.parcels');
    await user.click(screen.getByRole('button', { name: /import/i }));

    expect(await screen.findByText('Tracking job-9')).toBeInTheDocument();
    expect(mockStartImport).toHaveBeenCalledWith(
      'warehouse',
      expect.objectContaining({ schema_name: 'gis', table_name: 'parcels', srid_override: null }),
    );
  });

  it('sends the CRS entered for a table without an SRID as srid_override', async () => {
    mockListTables.mockResolvedValue(listing([table({ srid: null })]));
    mockStartImport.mockResolvedValue({ job_id: 'job-9', status: 'pending', message: 'queued' });
    const user = userEvent.setup();
    render(<DatabaseImportForm />);

    expect(await screen.findByText('No SRID')).toBeInTheDocument();
    await openReview(user, 'gis.parcels');
    expect(screen.getByText('This table has no SRID. Enter the EPSG code its coordinates use.')).toBeInTheDocument();
    expect(screen.queryByText(/Override the detected CRS/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/CRS/i), '3857');
    await user.click(screen.getByRole('button', { name: /import/i }));

    await waitFor(() =>
      expect(mockStartImport).toHaveBeenCalledWith(
        'warehouse',
        expect.objectContaining({ srid_override: 3857 }),
      ),
    );
  });

  it('reports a duplicate source and stays on the review step', async () => {
    mockListTables.mockResolvedValue(listing([table()]));
    mockStartImport.mockRejectedValue(
      new ApiError('duplicate', 409, {
        code: 'duplicate_source',
        existing_dataset_id: 'ds-1',
        existing_title: 'Parcels',
      }),
    );
    const user = userEvent.setup();
    render(<DatabaseImportForm />);

    await openReview(user, 'gis.parcels');
    await user.click(screen.getByRole('button', { name: /import/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Already imported: "Parcels"');
    expect(screen.queryByText(/Tracking/)).not.toBeInTheDocument();
  });

  it('reports a duplicate still being imported without a link to a dataset', async () => {
    const body = { code: 'duplicate_source', existing_job_id: 'job-7' };
    mockListTables.mockResolvedValue(listing([table()]));
    mockStartImport.mockRejectedValue(
      new ApiError(translateApiErrorDetail(body, 409), 409, body),
    );
    const user = userEvent.setup();
    render(<DatabaseImportForm />);

    await openReview(user, 'gis.parcels');
    await user.click(screen.getByRole('button', { name: /import/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This source is already being imported. Wait for that import to finish',
    );
    expect(toast.error).toHaveBeenCalledWith(expect.any(String));
    expect(screen.queryByText(/Tracking/)).not.toBeInTheDocument();
  });

  it('asks for a CRS from the row picked last, not an earlier one', async () => {
    mockListTables.mockResolvedValue(
      listing([table({ table_name: 'v_zones', srid: null }), table()]),
    );
    mockStartImport.mockResolvedValue({ job_id: 'job-9', status: 'pending', message: 'queued' });
    const user = userEvent.setup();
    render(<DatabaseImportForm />);

    await openReview(user, 'gis.v_zones');
    expect(screen.getByLabelText(/CRS/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/CRS/i), '3857');
    await user.click(screen.getByRole('button', { name: 'Back to tables' }));
    await openReview(user, 'gis.parcels');

    expect(screen.queryByLabelText(/CRS Override/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /import/i }));
    await waitFor(() =>
      expect(mockStartImport).toHaveBeenCalledWith(
        'warehouse',
        expect.objectContaining({ table_name: 'parcels', srid_override: null }),
      ),
    );
  });

  it('keeps an in-flight import across an unmount and tracks its job on return', async () => {
    mockListTables.mockResolvedValue(listing([table()]));
    let resolveImport!: (value: unknown) => void;
    mockStartImport.mockReturnValue(new Promise((resolve) => { resolveImport = resolve; }));
    const user = userEvent.setup();
    const first = render(<DatabaseImportForm />);

    await openReview(user, 'gis.parcels');
    await user.click(screen.getByRole('button', { name: /import/i }));
    first.unmount();
    resolveImport({ job_id: 'job-late', status: 'pending', message: 'queued' });

    render(<DatabaseImportForm />);

    expect(await screen.findByText('Tracking job-late')).toBeInTheDocument();
    expect(mockStartImport).toHaveBeenCalledTimes(1);
  });

  it('resumes a still-pending import when the form is mounted again', async () => {
    mockListTables.mockResolvedValue(listing([table()]));
    let resolveImport!: (value: unknown) => void;
    mockStartImport.mockReturnValue(new Promise((resolve) => { resolveImport = resolve; }));
    const user = userEvent.setup();
    const first = render(<DatabaseImportForm />);

    await openReview(user, 'gis.parcels');
    await user.click(screen.getByRole('button', { name: /import/i }));
    first.unmount();
    render(<DatabaseImportForm />);
    resolveImport({ job_id: 'job-pending', status: 'pending', message: 'queued' });

    expect(await screen.findByText('Tracking job-pending')).toBeInTheDocument();
  });

  it('offers Import another once the job completes, and drops the session for good', async () => {
    mockListTables.mockResolvedValue(listing([table()]));
    mockStartImport.mockResolvedValue({ job_id: 'job-9', status: 'pending', message: 'queued' });
    mockJobStatus.mockResolvedValue({ id: 'job-9', status: 'complete' });
    const user = userEvent.setup();
    const first = render(<DatabaseImportForm />);

    await openReview(user, 'gis.parcels');
    await user.click(screen.getByRole('button', { name: /import/i }));
    await user.click(await screen.findByRole('button', { name: 'Import another' }));

    expect(await screen.findByRole('radio', { name: /gis\.parcels/ })).toBeInTheDocument();
    first.unmount();
    render(<DatabaseImportForm />);
    expect(await screen.findByRole('radio', { name: /gis\.parcels/ })).toBeInTheDocument();
    expect(screen.queryByText(/Tracking/)).not.toBeInTheDocument();
  });

  it('does not offer Import another while the job is still running', async () => {
    mockListTables.mockResolvedValue(listing([table()]));
    mockStartImport.mockResolvedValue({ job_id: 'job-9', status: 'pending', message: 'queued' });
    const user = userEvent.setup();
    render(<DatabaseImportForm />);

    await openReview(user, 'gis.parcels');
    await user.click(screen.getByRole('button', { name: /import/i }));

    expect(await screen.findByText('Tracking job-9')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Import another' })).not.toBeInTheDocument();
  });

  it('lists a name the import refuses, disabled and with the reason', async () => {
    mockListTables.mockResolvedValue(
      listing([table({ table_name: 'odd]name', importable: false }), table()]),
    );
    render(<DatabaseImportForm />);

    const odd = await screen.findByRole('radio', { name: /odd\]name/ });
    expect(odd).toBeDisabled();
    expect(odd).toHaveAccessibleDescription("This name has characters GeoLens can't import.");
    expect(screen.getByRole('radio', { name: /gis\.parcels/ })).toBeEnabled();
  });

  it('keeps rows apart when their dotted names read the same', async () => {
    mockListTables.mockResolvedValue(
      listing([
        table({ schema_name: 'a.b', table_name: 'c' }),
        table({ schema_name: 'a', table_name: 'b.c' }),
      ]),
    );
    const user = userEvent.setup();
    render(<DatabaseImportForm />);

    const [first, second] = await screen.findAllByRole('radio');
    await user.click(second);
    await user.click(first);

    expect(first).toBeChecked();
    expect(second).not.toBeChecked();
    expect(first.closest('label')).toHaveClass('bg-primary/10');
    expect(second.closest('label')).not.toHaveClass('bg-primary/10');
  });

  it('drops the picked table when its connection leaves the deployment', async () => {
    withConnections('warehouse', 'archive');
    mockListTables.mockResolvedValue(listing([table()]));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const user = userEvent.setup();
    renderBare(<DatabaseImportForm />, { wrapper });

    await user.click(await screen.findByRole('radio', { name: /archive/ }));
    await user.click(await screen.findByRole('radio', { name: /gis\.parcels/ }));
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();

    withConnections('warehouse');
    await queryClient.invalidateQueries({ queryKey: ['capabilities'] });

    await waitFor(() => expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled());
  });

  it('ignores a pending import that finishes after the account changed', async () => {
    useAuthStore.setState({ user: { id: 'u1', roles: [] } as never });
    mockListTables.mockResolvedValue(listing([table()]));
    let resolveImport!: (value: unknown) => void;
    mockStartImport.mockReturnValue(new Promise((resolve) => { resolveImport = resolve; }));
    const user = userEvent.setup();
    render(<DatabaseImportForm />);

    await openReview(user, 'gis.parcels');
    await user.click(screen.getByRole('button', { name: /import/i }));
    useAuthStore.setState({ user: { id: 'u2', roles: [] } as never });
    resolveImport({ job_id: 'job-old', status: 'pending', message: 'queued' });

    expect(await screen.findByRole('radio', { name: /gis\.parcels/ })).toBeInTheDocument();
    expect(screen.queryByText(/Tracking/)).not.toBeInTheDocument();
    useAuthStore.setState({ user: null });
  });

  it('restores the reviewed values when a start failed while the tab was away', async () => {
    mockListTables.mockResolvedValue(listing([table()]));
    let rejectImport!: (reason: unknown) => void;
    mockStartImport.mockReturnValue(new Promise((_, reject) => { rejectImport = reject; }));
    const user = userEvent.setup();
    const first = render(<DatabaseImportForm />);

    await openReview(user, 'gis.parcels');
    const title = screen.getByDisplayValue('parcels');
    await user.clear(title);
    await user.type(title, 'My parcels');
    await user.click(screen.getByRole('button', { name: /import/i }));
    first.unmount();
    rejectImport(new ApiError('Server said no', 500));
    await Promise.resolve();

    render(<DatabaseImportForm />);

    expect(await screen.findByDisplayValue('My parcels')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Server said no');
  });
});
