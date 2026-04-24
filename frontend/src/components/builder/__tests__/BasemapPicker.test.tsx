import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { BasemapPicker } from '../BasemapPicker';
import type { BasemapEntry } from '@/api/settings';

const mockBasemaps: BasemapEntry[] = [
  { id: 'openfreemap-positron', label: 'Positron', url: 'https://example.com/positron', enabled: true, is_preset: true },
  { id: 'openfreemap-dark', label: 'Dark', url: 'https://example.com/dark', enabled: true, is_preset: true },
  { id: 'openstreetmap', label: 'OSM', url: 'https://example.com/osm', enabled: true, is_preset: true },
  { id: 'openfreemap-bright', label: 'Bright', url: 'https://example.com/bright', enabled: true, is_preset: true },
];

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: vi.fn(() => ({ data: mockBasemaps })),
}));

// Mock static PNG imports — Vite resolves these to URL strings
vi.mock('@/assets/basemaps/positron.png', () => ({ default: '/assets/positron.png' }));
vi.mock('@/assets/basemaps/dark.png', () => ({ default: '/assets/dark.png' }));
vi.mock('@/assets/basemaps/osm.png', () => ({ default: '/assets/osm.png' }));
vi.mock('@/assets/basemaps/bright.png', () => ({ default: '/assets/bright.png' }));

describe('BasemapPicker', () => {
  it('renders collapsed with current basemap label', () => {
    render(<BasemapPicker value="openfreemap-positron" onChange={vi.fn()} />);
    expect(screen.getByText('Positron')).toBeInTheDocument();
  });

  it('uses static PNG for built-in basemap thumbnail', () => {
    render(<BasemapPicker value="openfreemap-positron" onChange={vi.fn()} />);
    const img = screen.getByAltText('Positron');
    expect(img).toHaveAttribute('src', '/assets/positron.png');
  });

  it('expands grid on click and shows all enabled basemaps', async () => {
    const user = userEvent.setup();
    render(<BasemapPicker value="openfreemap-positron" onChange={vi.fn()} />);

    await user.click(screen.getByText('Positron'));
    const options = screen.getAllByTestId('basemap-option');
    // 4 enabled basemaps + 1 synthetic "None" blank entry prepended
    expect(options).toHaveLength(5);
  });

  it('calls onChange and closes on basemap selection', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<BasemapPicker value="openfreemap-positron" onChange={onChange} />);

    await user.click(screen.getByText('Positron'));
    await user.click(screen.getByText('Dark'));
    expect(onChange).toHaveBeenCalledWith('openfreemap-dark');
    expect(screen.queryAllByTestId('basemap-option')).toHaveLength(0);
  });

  it('uses SVG fallback for unknown basemap IDs', () => {
    render(<BasemapPicker value="custom-xyz" onChange={vi.fn()} />);
    // Collapsed thumbnail for an unknown ID should use the SVG fallback
    const imgs = screen.getAllByRole('img');
    const collapsed = imgs[0];
    expect(collapsed.getAttribute('src')).toContain('data:image/svg+xml');
  });
});
