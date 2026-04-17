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
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
    thumbnail_url: '/api/maps/map-1/thumbnail/',
    created_by_username: 'testuser',
    ...overrides,
  };
}

describe('MapCard', () => {
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
