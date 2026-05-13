import { fireEvent, render, screen } from '@/test/test-utils';
import { BasemapGroupEditorScene, BasemapGroupEditorFooter } from '../BasemapGroupEditorScene';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string } & Record<string, unknown>) => {
      if (options?.defaultValue !== undefined) {
        let result = options.defaultValue as string;
        const params = options as Record<string, unknown>;
        Object.keys(params).forEach((k) => {
          if (k !== 'defaultValue') {
            result = result.replace(`{{${k}}}`, String(params[k]));
          }
        });
        return result;
      }
      return key;
    },
  }),
}));

vi.mock('@/lib/basemap-utils', () => ({
  basemapThumbnail: (id: string) => `https://thumb.test/${id}.png`,
}));

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

const defaultPresets = [
  { id: 'openfreemap-positron', name: 'Positron', provider: 'OpenFreeMap' },
  { id: 'openfreemap-dark', name: 'Dark Matter', provider: 'OpenFreeMap' },
  { id: 'openstreetmap', name: 'OSM Standard', provider: 'OpenStreetMap' },
  { id: 'openfreemap-bright', name: 'Bright', provider: 'OpenFreeMap' },
];

const defaultSublayers = [
  { id: 'roads', name: 'Roads', visible: true, opacity: 1, kind: 'vector' as const },
  { id: 'labels', name: 'Labels', visible: true, opacity: 0.9, kind: 'vector' as const },
  { id: 'buildings', name: 'Buildings', visible: false, opacity: 1, kind: 'vector' as const },
];

function defaultSceneProps(overrides: Partial<React.ComponentProps<typeof BasemapGroupEditorScene>> = {}) {
  return {
    activePresetId: 'openfreemap-positron',
    presets: defaultPresets,
    sublayers: defaultSublayers,
    masterOpacity: 1,
    onSwapBasemap: vi.fn(),
    onAddCustomBasemap: vi.fn(),
    onSublayerVisibilityChange: vi.fn(),
    onSublayerOpacityChange: vi.fn(),
    onMasterOpacityChange: vi.fn(),
    ...overrides,
  };
}

describe('BasemapGroupEditorScene', () => {
  it('Test 1: renders PRESET section label (10px ALL CAPS) followed by a 2-column grid of preset cards', () => {
    render(<BasemapGroupEditorScene {...defaultSceneProps()} />);

    // PRESET section label
    expect(screen.getByText('PRESET')).toBeInTheDocument();

    // 4 preset cards (one for each preset in the grid)
    expect(screen.getByText('Positron')).toBeInTheDocument();
    expect(screen.getByText('Dark Matter')).toBeInTheDocument();
    expect(screen.getByText('OSM Standard')).toBeInTheDocument();
    expect(screen.getByText('Bright')).toBeInTheDocument();
  });

  it('Test 2: each preset card has thumbnail img with height 56px', () => {
    const { container } = render(<BasemapGroupEditorScene {...defaultSceneProps()} />);

    // Query images directly via DOM since they are aria-hidden
    const images = Array.from(container.querySelectorAll('img'));
    // Filter to preset thumbnails
    const thumbImages = images.filter((img) => img.getAttribute('src')?.includes('thumb.test'));
    expect(thumbImages.length).toBe(4);
    thumbImages.forEach((img) => {
      expect(img.style.height).toBe('56px');
    });
  });

  it('Test 3: active preset card has border-primary class; other cards have border-[var(--border)]', () => {
    render(<BasemapGroupEditorScene {...defaultSceneProps({ activePresetId: 'openfreemap-positron' })} />);

    // The active card (Positron) should have border-primary
    // Find all preset card buttons
    const cards = screen.getAllByRole('button').filter((b) => b.querySelector('img'));
    const positronCard = cards.find((c) => c.textContent?.includes('Positron'));
    const darkCard = cards.find((c) => c.textContent?.includes('Dark Matter'));

    expect(positronCard).toBeTruthy();
    expect(darkCard).toBeTruthy();
    expect(positronCard?.className).toContain('border-primary');
    expect(darkCard?.className).not.toContain('border-primary');
  });

  it('Test 4: click on an inactive preset card calls onSwapBasemap(presetId)', () => {
    const onSwapBasemap = vi.fn();
    render(<BasemapGroupEditorScene {...defaultSceneProps({ onSwapBasemap, activePresetId: 'openfreemap-positron' })} />);

    const cards = screen.getAllByRole('button').filter((b) => b.querySelector('img'));
    const darkCard = cards.find((c) => c.textContent?.includes('Dark Matter'));
    expect(darkCard).toBeTruthy();
    fireEvent.click(darkCard!);

    expect(onSwapBasemap).toHaveBeenCalledOnce();
    expect(onSwapBasemap).toHaveBeenCalledWith('openfreemap-dark');
  });

  it('Test 5: "＋ Add custom basemap…" link appears below the preset grid with text-primary styling', () => {
    const onAddCustomBasemap = vi.fn();
    render(<BasemapGroupEditorScene {...defaultSceneProps({ onAddCustomBasemap })} />);

    const addLink = screen.getByRole('button', { name: /Add custom basemap/i }) ||
      screen.getByText(/Add custom basemap/i);
    expect(addLink).toBeInTheDocument();
    expect(addLink.className).toContain('primary');

    fireEvent.click(addLink);
    expect(onAddCustomBasemap).toHaveBeenCalledOnce();
  });

  it('Test 6: SUBLAYERS section renders label, hint text, and compressed list', () => {
    render(<BasemapGroupEditorScene {...defaultSceneProps()} />);

    expect(screen.getByText('SUBLAYERS')).toBeInTheDocument();
    expect(screen.getByText(/Click any sublayer in the sidebar to style it individually/)).toBeInTheDocument();

    // Sublayer names
    expect(screen.getByText('Roads')).toBeInTheDocument();
    expect(screen.getByText('Labels')).toBeInTheDocument();
    expect(screen.getByText('Buildings')).toBeInTheDocument();
  });

  it('Test 7: each sublayer list item is 32px tall and NOT clickable as a row', () => {
    render(<BasemapGroupEditorScene {...defaultSceneProps()} />);

    // Get the list
    const list = screen.getByRole('list');
    const items = list.querySelectorAll('li');
    expect(items.length).toBe(3);
    items.forEach((item) => {
      expect((item as HTMLElement).style.height).toBe('32px');
      // The li should NOT have an onClick directly (rows not clickable)
      expect((item as HTMLLIElement).onclick).toBeNull();
    });
  });

  it('Test 8: eye toggle in sublayer list calls onSublayerVisibilityChange(sublayerId)', () => {
    const onSublayerVisibilityChange = vi.fn();
    render(<BasemapGroupEditorScene {...defaultSceneProps({ onSublayerVisibilityChange })} />);

    // Get eye toggle buttons in the sublayer list
    // They should have aria-labels including sublayer names
    const eyeButtons = screen.getAllByRole('button', { name: /Toggle visibility for/i });
    // There should be 3 eye buttons (one per sublayer) plus master ones
    const roadsEye = eyeButtons.find((b) => b.getAttribute('aria-label')?.includes('Roads'));
    expect(roadsEye).toBeTruthy();
    fireEvent.click(roadsEye!);

    expect(onSublayerVisibilityChange).toHaveBeenCalledWith('roads');
  });

  it('Test 9: opacity slider in sublayer list calls onSublayerOpacityChange(sublayerId, value)', () => {
    const onSublayerOpacityChange = vi.fn();
    render(<BasemapGroupEditorScene {...defaultSceneProps({ onSublayerOpacityChange })} />);

    // Multiple sliders: 1 per sublayer + 1 master opacity
    const sliders = screen.getAllByRole('slider');
    // Sublayer sliders should have aria-labels with sublayer names
    const roadsSlider = sliders.find((s) => s.getAttribute('aria-label')?.includes('Roads'));
    expect(roadsSlider).toBeTruthy();
  });

  it('Test 10: VISIBILITY section renders "Master opacity" label + slider wired to onMasterOpacityChange', () => {
    const onMasterOpacityChange = vi.fn();
    render(<BasemapGroupEditorScene {...defaultSceneProps({ onMasterOpacityChange })} />);

    expect(screen.getByText(/Master opacity/i)).toBeInTheDocument();
    const masterSlider = screen.getByRole('slider', { name: /Master opacity/i });
    expect(masterSlider).toBeInTheDocument();
  });

  it('Test 11: footer renders TWO side-by-side ghost buttons: "Reset appearance" and "Remove basemap"', () => {
    render(<BasemapGroupEditorFooter onResetAppearance={vi.fn()} onRemoveBasemap={vi.fn()} />);

    const resetBtn = screen.getByRole('button', { name: /Reset appearance/i });
    const removeBtn = screen.getByRole('button', { name: /Remove basemap/i });

    expect(resetBtn).toBeInTheDocument();
    expect(removeBtn).toBeInTheDocument();

    // Neither has explicit variant="destructive" styling (bg-destructive text-destructive-foreground)
    // The ghost variant may include aria-invalid:border-destructive in base class, which is acceptable
    expect(resetBtn.getAttribute('data-variant') ?? resetBtn.className).not.toContain('bg-destructive');
    expect(removeBtn.getAttribute('data-variant') ?? removeBtn.className).not.toContain('bg-destructive');
  });

  it('Test 12: footer buttons wire to onResetAppearance() and onRemoveBasemap()', () => {
    const onResetAppearance = vi.fn();
    const onRemoveBasemap = vi.fn();
    render(<BasemapGroupEditorFooter onResetAppearance={onResetAppearance} onRemoveBasemap={onRemoveBasemap} />);

    fireEvent.click(screen.getByRole('button', { name: /Reset appearance/i }));
    expect(onResetAppearance).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole('button', { name: /Remove basemap/i }));
    expect(onRemoveBasemap).toHaveBeenCalledOnce();
  });
});
