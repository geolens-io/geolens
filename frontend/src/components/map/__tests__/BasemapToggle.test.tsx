import { render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { BasemapToggle } from '../BasemapToggle';

const mockBasemaps = [
  { id: 'positron', label: 'Positron', url: 'https://example.com/positron', enabled: true, is_preset: true },
  { id: 'dark', label: 'Dark', url: 'https://example.com/dark', enabled: true, is_preset: true },
  { id: 'satellite', label: 'Satellite', url: 'https://example.com/sat', enabled: true, is_preset: true },
  { id: 'disabled-one', label: 'Disabled', url: 'https://example.com/x', enabled: false, is_preset: true },
];

const mockUseBasemaps = vi.fn((..._args: unknown[]) => ({ data: mockBasemaps }));

vi.mock('@/hooks/use-settings', () => ({
  useBasemaps: (...args: unknown[]) => mockUseBasemaps(...args),
}));

vi.mock('@/lib/basemap-utils', () => ({
  basemapThumbnail: vi.fn((id: string) => `/thumbs/${id}.png`),
}));

describe('BasemapToggle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseBasemaps.mockReturnValue({ data: mockBasemaps });
  });

  it('renders trigger button with current basemap thumbnail', () => {
    render(<BasemapToggle value="positron" onChange={vi.fn()} />);

    const button = screen.getByRole('button', { name: 'Change basemap' });
    expect(button).toBeInTheDocument();

    const img = screen.getByAltText('Positron');
    expect(img).toHaveAttribute('src', '/thumbs/positron.png');
  });

  it('returns null when only one basemap is enabled', () => {
    const singleBasemap = [{ id: 'positron', label: 'Positron', url: '', enabled: true, is_preset: true }];
    mockUseBasemaps.mockReturnValue({ data: singleBasemap });

    const { container } = render(<BasemapToggle value="positron" onChange={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it('opens popover on click and shows enabled basemaps', async () => {
    const user = userEvent.setup();
    render(<BasemapToggle value="positron" onChange={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Change basemap' }));

    // Should show 3 enabled basemaps (not the disabled one)
    expect(screen.getByText('Positron')).toBeInTheDocument();
    expect(screen.getByText('Dark')).toBeInTheDocument();
    expect(screen.getByText('Satellite')).toBeInTheDocument();
    expect(screen.queryByText('Disabled')).not.toBeInTheDocument();
  });

  it('calls onChange and closes popover on basemap selection', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<BasemapToggle value="positron" onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: 'Change basemap' }));
    await user.click(screen.getByRole('button', { name: 'Dark' }));

    expect(onChange).toHaveBeenCalledWith('dark');
    // Popover should close — other basemap labels should disappear
    expect(screen.queryByText('Satellite')).not.toBeInTheDocument();
  });
});
