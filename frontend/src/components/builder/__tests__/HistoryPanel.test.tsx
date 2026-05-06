import { render, screen } from '@/test/test-utils';
import { useMapHistory } from '@/hooks/use-maps';
import { HistoryPanel } from '../HistoryPanel';
import type { MapHistoryEntryResponse, MapHistoryListResponse } from '@/types/api';

vi.mock('@/hooks/use-maps', () => ({
  useMapHistory: vi.fn(),
}));

const mockedUseMapHistory = vi.mocked(useMapHistory);

function mockHistoryQuery(overrides: {
  data?: MapHistoryListResponse;
  isLoading?: boolean;
  isError?: boolean;
} = {}) {
  mockedUseMapHistory.mockReturnValue({
    data: overrides.data,
    isLoading: overrides.isLoading ?? false,
    isError: overrides.isError ?? false,
  } as never);
}

function makeEvent(overrides: Partial<MapHistoryEntryResponse> = {}): MapHistoryEntryResponse {
  return {
    id: 'event-1',
    map_id: 'map-1',
    actor_id: 'user-1',
    actor_username: 'alice',
    target_type: 'layer',
    target_id: 'layer-1',
    target_name: 'Population',
    action: 'layer.style_update',
    summary: 'Changed ramp to OrRd',
    details: {},
    created_at: '2026-05-06T11:55:00Z',
    ...overrides,
  };
}

describe('HistoryPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-05-06T12:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders a loading state', () => {
    mockHistoryQuery({ isLoading: true });

    render(<HistoryPanel mapId="map-1" />);

    expect(screen.getByRole('status')).toHaveTextContent('Loading history...');
    expect(mockedUseMapHistory).toHaveBeenCalledWith('map-1', 0, 50);
  });

  it('renders an empty state', () => {
    mockHistoryQuery({ data: { events: [], total: 0, skip: 0, limit: 50 } });

    render(<HistoryPanel mapId="map-1" />);

    expect(screen.getByText('No edit history yet')).toBeInTheDocument();
    expect(
      screen.getByText('History starts after saved edits are recorded for this map.'),
    ).toBeInTheDocument();
  });

  it('renders an error state', () => {
    mockHistoryQuery({ isError: true });

    render(<HistoryPanel mapId="map-1" />);

    expect(screen.getByRole('alert')).toHaveTextContent('History could not be loaded');
  });

  it('renders populated history entries with relative time and summary text', () => {
    mockHistoryQuery({
      data: {
        total: 2,
        skip: 0,
        limit: 50,
        events: [
          makeEvent(),
          makeEvent({
            id: 'event-2',
            actor_id: null,
            actor_username: null,
            target_type: 'map',
            target_id: null,
            target_name: null,
            action: 'map.rename',
            summary: 'Renamed map',
            created_at: '2026-05-06T10:00:00Z',
          }),
        ],
      },
    });

    render(<HistoryPanel mapId="map-1" />);

    expect(screen.getByText('Changed ramp to OrRd')).toBeInTheDocument();
    expect(screen.getByText('Renamed map')).toBeInTheDocument();
    expect(screen.getByText('5 minutes ago')).toHaveAttribute('datetime', '2026-05-06T11:55:00Z');
    expect(screen.getByText('alice - Population')).toBeInTheDocument();
    expect(screen.getByText('Unknown user')).toBeInTheDocument();
  });
});
