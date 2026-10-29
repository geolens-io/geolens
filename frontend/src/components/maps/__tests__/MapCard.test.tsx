import { fireEvent, render, screen } from '@/test/test-utils';
import type { MapSummaryResponse } from '@/types/api';
import { vi } from 'vitest';
import { MapCard } from '../MapCard';
import { MapCardGrid } from '../MapCardGrid';

vi.mock('@/components/maps/hooks/use-map-thumbnail', () => ({
  useMapThumbnail: vi.fn(),
}));

import { useMapThumbnail } from '@/components/maps/hooks/use-map-thumbnail';

const mockUseMapThumbnail = vi.mocked(useMapThumbnail);

function makeMap(overrides: Partial<MapSummaryResponse> = {}): MapSummaryResponse {
  return {
    id: 'map-1',
    name: 'Test Map',
    description: null,
    visibility: 'private',
    layer_count: 2,
    has_dashboard: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    thumbnail_url: '/api/maps/map-1/thumbnail/',
    thumbnail_updated_at: null,
    created_by_username: 'testuser',
    ...overrides,
  };
}

describe('MapCard', () => {
  it.each([
    ['list', MapCard],
    ['grid', MapCardGrid],
  ])('badges a map that shows the reader a dashboard in the %s view', (_view, Card) => {
    mockUseMapThumbnail.mockReturnValue(null);
    const { rerender } = render(<Card map={makeMap()} onDelete={() => {}} />);
    expect(screen.queryByText('Dashboard')).not.toBeInTheDocument();
    rerender(<Card map={makeMap({ has_dashboard: true })} onDelete={() => {}} />);
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
  });

  it('renders img when thumbnail is present and no error', () => {
    mockUseMapThumbnail.mockReturnValue('blob:http://localhost/fake-thumb');
    render(<MapCard map={makeMap()} onDelete={() => {}} />);
    expect(screen.getByRole('img')).toBeInTheDocument();
  });

  it('renders MapIcon placeholder when thumbnail_url is null', () => {
    mockUseMapThumbnail.mockReturnValue(null);
    render(<MapCard map={makeMap({ thumbnail_url: null })} onDelete={() => {}} />);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Test Map preview' })).toBeInTheDocument();
  });

  it('renders MapIcon placeholder when img fires onError (simulating 404)', () => {
    mockUseMapThumbnail.mockReturnValue('blob:http://localhost/fake-thumb');
    render(<MapCard map={makeMap()} onDelete={() => {}} />);
    const img = screen.getByRole('img');
    fireEvent.error(img);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
});

// MapVisibility = 'public' | 'internal' | 'private' (maps do not use 'restricted')
describe('MapCard visibility labels', () => {
  beforeEach(() => {
    mockUseMapThumbnail.mockReturnValue(null);
  });

  it.each([
    ['public', 'Public'],
    ['internal', 'Internal'],
    ['private', 'Private'],
  ] as const)(
    'renders visible %s label in the DOM without any hover event',
    (visibility, expectedLabel) => {
      render(<MapCard map={makeMap({ visibility })} />);
      // Text must be present on initial render — no fireEvent/pointer interaction
      expect(screen.getByText(expectedLabel)).toBeInTheDocument();
    },
  );

  it('renders distinct visible text for internal and private (GLUX-005)', () => {
    const { unmount } = render(<MapCard map={makeMap({ visibility: 'internal' })} />);
    const internalLabel = screen.getByText('Internal').textContent ?? '';
    unmount();

    render(<MapCard map={makeMap({ visibility: 'private' })} />);
    const privateLabel = screen.getByText('Private').textContent ?? '';

    expect(internalLabel).not.toBe(privateLabel);
  });
});

describe('MapCardGrid', () => {
  it('renders img when thumbnail is present and no error', () => {
    mockUseMapThumbnail.mockReturnValue('blob:http://localhost/fake-thumb');
    render(<MapCardGrid map={makeMap()} onDelete={() => {}} />);
    expect(screen.getByRole('img')).toBeInTheDocument();
  });

  it('renders MapIcon placeholder when thumbnail_url is null', () => {
    mockUseMapThumbnail.mockReturnValue(null);
    render(<MapCardGrid map={makeMap({ thumbnail_url: null })} onDelete={() => {}} />);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Test Map preview' })).toBeInTheDocument();
  });

  it('renders MapIcon placeholder when img fires onError (simulating 404)', () => {
    mockUseMapThumbnail.mockReturnValue('blob:http://localhost/fake-thumb');
    render(<MapCardGrid map={makeMap()} onDelete={() => {}} />);
    const img = screen.getByRole('img');
    fireEvent.error(img);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
});

// The thumbnail cache version is not `updated_at`, which carries two
// meanings — a lazy backfill on first builder open would reorder the
// "Last updated" gallery for what is a read.
describe.each([
  ['MapCard', MapCard],
  ['MapCardGrid', MapCardGrid],
])('%s thumbnail cache version', (_name, Component) => {
  beforeEach(() => {
    mockUseMapThumbnail.mockReturnValue('blob:http://localhost/fake-thumb');
  });

  it("versions on the thumbnail's own timestamp when it has one", () => {
    render(
      <Component
        map={makeMap({ thumbnail_updated_at: '2026-03-04T05:06:07Z' })}
        onDelete={() => {}}
      />,
    );

    expect(mockUseMapThumbnail).toHaveBeenCalledWith(
      '/api/maps/map-1/thumbnail/',
      '2026-03-04T05:06:07Z',
    );
  });

  it('falls back to updated_at for a thumbnail captured before the column existed', () => {
    render(<Component map={makeMap({ thumbnail_updated_at: null })} onDelete={() => {}} />);

    expect(mockUseMapThumbnail).toHaveBeenCalledWith(
      '/api/maps/map-1/thumbnail/',
      '2026-01-02T00:00:00Z',
    );
  });
});
