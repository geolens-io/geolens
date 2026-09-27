import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { AddToMapButton } from '@/components/dataset/AddToMapButton';
import { toast } from 'sonner';

const mockNavigate = vi.fn();
vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockMutateAsync = vi.fn();
const mockCan = vi.fn();
vi.mock('@/hooks/use-permissions', () => ({
  usePermissions: () => ({ can: mockCan }),
}));
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }));
const mockMapsData = vi.hoisted(() => ({
  maps: [] as Array<{ id: string; name: string; created_by?: string | null }>,
  isLoading: false,
  isPending: false,
}));

const auth = vi.hoisted(() => ({ user: { id: 'user-1', roles: ['viewer'] } }));
const queryParams = vi.hoisted(() => vi.fn());
vi.mock('@/stores/auth-store', () => ({ useAuthStore: (selector: (state: typeof auth) => unknown) => selector(auth) }));

vi.mock('@/hooks/use-maps', () => ({
  useMaps: (params: unknown) => {
    queryParams(params);
    return { data: { maps: mockMapsData.maps }, isLoading: mockMapsData.isLoading };
  },
  useCreateMap: () => ({
    mutateAsync: mockMutateAsync,
    isPending: mockMapsData.isPending,
  }),
}));

describe('AddToMapButton', () => {
  const user = userEvent.setup();

  beforeEach(() => {
    mockNavigate.mockReset();
    mockMutateAsync.mockReset();
    mockMapsData.maps = [];
    mockMapsData.isLoading = false;
    mockMapsData.isPending = false;
    mockCan.mockReset();
    mockCan.mockReturnValue(true);
    vi.mocked(toast.error).mockClear();
    auth.user.roles = ['viewer'];
    queryParams.mockClear();
  });

  it('renders the trigger button', () => {
    render(<AddToMapButton datasetId="ds-1" />);
    expect(screen.getByRole('button', { name: /Add to Map/i })).toBeInTheDocument();
  });

  it('shows "No maps available" when no maps exist', async () => {
    render(<AddToMapButton datasetId="ds-1" />);
    await user.click(screen.getByRole('button', { name: /Add to Map/i }));

    expect(screen.getByRole('menuitem', { name: /No maps available/i })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /New map/i })).toBeInTheDocument();
  });

  it('lists existing maps in dropdown', async () => {
    mockMapsData.maps = [
      { id: 'map-1', name: 'My First Map', created_by: 'user-1' },
      { id: 'map-2', name: 'Another Map', created_by: 'user-1' },
    ];

    render(<AddToMapButton datasetId="ds-1" />);
    await user.click(screen.getByRole('button', { name: /Add to Map/i }));

    expect(screen.getByRole('menuitem', { name: 'My First Map' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Another Map' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /New map/i })).toBeInTheDocument();
  });

  it('navigates to existing map builder with add_dataset param', async () => {
    mockMapsData.maps = [{ id: 'map-1', name: 'Test Map', created_by: 'user-1' }];

    render(<AddToMapButton datasetId="ds-1" />);
    await user.click(screen.getByRole('button', { name: /Add to Map/i }));
    await user.click(screen.getByRole('menuitem', { name: 'Test Map' }));

    expect(mockNavigate).toHaveBeenCalledWith('/maps/map-1?add_dataset=ds-1');
  });

  it('creates new map and navigates to builder on "+ New map"', async () => {
    mockMutateAsync.mockResolvedValue({ id: 'new-map-id' });

    render(<AddToMapButton datasetId="ds-1" datasetTitle="My Dataset" />);
    await user.click(screen.getByRole('button', { name: /Add to Map/i }));
    await user.click(screen.getByRole('menuitem', { name: /New map/i }));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({ name: 'My Dataset Map' });
      expect(mockNavigate).toHaveBeenCalledWith('/maps/new-map-id?add_dataset=ds-1');
    });
  });

  it('uses "New Map" as fallback name when datasetTitle is not provided', async () => {
    mockMutateAsync.mockResolvedValue({ id: 'new-map-id' });

    render(<AddToMapButton datasetId="ds-1" />);
    await user.click(screen.getByRole('button', { name: /Add to Map/i }));
    await user.click(screen.getByRole('menuitem', { name: /New map/i }));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({ name: 'New Map' });
    });
  });

  it('does not navigate on API failure', async () => {
    mockMutateAsync.mockRejectedValue(new Error('Server error'));

    render(<AddToMapButton datasetId="ds-1" />);
    await user.click(screen.getByRole('button', { name: /Add to Map/i }));
    await user.click(screen.getByRole('menuitem', { name: /New map/i }));

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalled();
    });
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('hides the map mutation entry point without the effective capability', () => {
    mockCan.mockReturnValue(false);
    mockMapsData.maps = [{ id: 'map-1', name: 'Existing Map' }];

    render(<AddToMapButton datasetId="ds-1" />);
    expect(mockCan).toHaveBeenCalledWith('edit_metadata');
    expect(screen.queryByRole('button', { name: /Add to Map/i })).not.toBeInTheDocument();
  });

  it('requests owned maps before pagination and excludes nonowner choices', async () => {
    mockMapsData.maps = [
      { id: 'map-1', name: 'Owned map', created_by: 'user-1' },
      { id: 'map-2', name: 'Other map', created_by: 'user-2' },
    ];
    render(<AddToMapButton datasetId="ds-1" />);
    await user.click(screen.getByRole('button', { name: /Add to Map/i }));
    expect(queryParams).toHaveBeenCalledWith(expect.objectContaining({ owned_only: true }));
    expect(screen.getByRole('menuitem', { name: 'Owned map' })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Other map' })).not.toBeInTheDocument();
  });

  it('allows admins to choose maps owned by other users', async () => {
    auth.user.roles = ['admin'];
    mockMapsData.maps = [{ id: 'map-2', name: 'Other map', created_by: 'user-2' }];
    render(<AddToMapButton datasetId="ds-1" />);
    await user.click(screen.getByRole('button', { name: /Add to Map/i }));
    expect(queryParams).toHaveBeenCalledWith(expect.objectContaining({ owned_only: false }));
    expect(screen.getByRole('menuitem', { name: 'Other map' })).toBeInTheDocument();
  });
});
