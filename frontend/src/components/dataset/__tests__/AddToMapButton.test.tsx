import { render, screen, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { AddToMapButton } from '@/components/dataset/AddToMapButton';

const mockNavigate = vi.fn();
vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockMutateAsync = vi.fn();
const mockMapsData = vi.hoisted(() => ({
  maps: [] as Array<{ id: string; name: string }>,
  isLoading: false,
  isPending: false,
}));

vi.mock('@/hooks/use-maps', () => ({
  useMaps: () => ({
    data: { maps: mockMapsData.maps },
    isLoading: mockMapsData.isLoading,
  }),
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
      { id: 'map-1', name: 'My First Map' },
      { id: 'map-2', name: 'Another Map' },
    ];

    render(<AddToMapButton datasetId="ds-1" />);
    await user.click(screen.getByRole('button', { name: /Add to Map/i }));

    expect(screen.getByRole('menuitem', { name: 'My First Map' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Another Map' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /New map/i })).toBeInTheDocument();
  });

  it('navigates to existing map builder with add_dataset param', async () => {
    mockMapsData.maps = [{ id: 'map-1', name: 'Test Map' }];

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
  });
});
