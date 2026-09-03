import { fireEvent, render, screen } from '@/test/test-utils';
import { RasterStretchControls } from '../RasterStretchControls';

/**
 * Direct coverage for the COLORMAP / STRETCH section.
 *
 * fix(#915): these gating, clamping, and sigma cases used to be exercised
 * through the (now deleted) RasterEditor wrapper. `RasterLayerControls.test.tsx`
 * never supplies `bandCount`, so this child returns null there and none of it
 * would be covered — these are the ported cases, aimed at the live component.
 */

// Mock shadcn Select to a native <select> so fireEvent.change works without a
// portal/Radix runtime in jsdom.
vi.mock('@/components/ui/select', async () => {
  const { createElement, Fragment } = await import('react');
  const Select = ({ value, onValueChange, children }: {
    value: string;
    onValueChange: (v: string) => void;
    children: React.ReactNode;
  }) =>
    createElement(
      'select',
      { 'data-slot': 'select', value, onChange: (e: React.ChangeEvent<HTMLSelectElement>) => onValueChange(e.target.value) },
      children,
    );
  const SelectTrigger = ({ children }: { children: React.ReactNode }) => createElement(Fragment, null, children);
  const SelectValue = () => null;
  const SelectContent = ({ children }: { children: React.ReactNode }) => createElement(Fragment, null, children);
  const SelectItem = ({ value, children, disabled }: {
    value: string;
    children: React.ReactNode;
    disabled?: boolean;
  }) => createElement('option', { value, disabled }, children);
  return { Select, SelectTrigger, SelectValue, SelectContent, SelectItem };
});

const t = ((key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key) as
  Parameters<typeof RasterStretchControls>[0]['t'];

function renderControls(
  bandCount: number | null | undefined,
  paint: Record<string, unknown> = {},
  onPaintProp = vi.fn(),
  isDem = false,
) {
  const result = render(
    <RasterStretchControls bandCount={bandCount} paint={paint} onPaintProp={onPaintProp} isDem={isDem} t={t} />,
  );
  return { ...result, onPaintProp };
}

describe('RasterStretchControls — gating', () => {
  it('renders both selects for a single-band raster', () => {
    renderControls(1);
    expect(screen.getAllByRole('combobox')).toHaveLength(2);
  });

  it('renders the stretch select but no colormap for multi-band', () => {
    renderControls(3);
    expect(screen.getAllByRole('combobox')).toHaveLength(1);
  });

  it('renders nothing when the band count is unknown or the layer is a DEM', () => {
    const { unmount } = renderControls(null);
    expect(screen.queryAllByRole('combobox')).toHaveLength(0);
    unmount();
    renderControls(undefined);
    expect(screen.queryAllByRole('combobox')).toHaveLength(0);
    renderControls(1, {}, vi.fn(), true);
    expect(screen.queryAllByRole('combobox')).toHaveLength(0);
  });
});

describe('RasterStretchControls — selects', () => {
  it('offers the 8 colormaps and the 3 stretch modes, all enabled', () => {
    renderControls(1);
    const [colormap, stretch] = screen.getAllByRole('combobox') as HTMLSelectElement[];
    expect(colormap.querySelectorAll('option')).toHaveLength(8);
    const stretchOptions = Array.from(stretch.querySelectorAll('option'));
    expect(stretchOptions.map((o) => o.value)).toEqual(['minmax', 'percentile', 'stddev']);
    expect(stretchOptions.every((o) => !o.disabled)).toBe(true);
  });

  it('emits _colormap and _stretch on change', () => {
    const onPaintProp = vi.fn();
    renderControls(1, {}, onPaintProp);
    const [colormap, stretch] = screen.getAllByRole('combobox');
    fireEvent.change(colormap, { target: { value: 'viridis' } });
    expect(onPaintProp).toHaveBeenCalledWith('_colormap', 'viridis');
    fireEvent.change(stretch, { target: { value: 'percentile' } });
    expect(onPaintProp).toHaveBeenCalledWith('_stretch', 'percentile');
  });
});

describe('RasterStretchControls — percentile bounds', () => {
  it('shows the low/high inputs only for the percentile stretch', () => {
    const { unmount } = renderControls(1, { _stretch: 'percentile' });
    expect(screen.getAllByRole('spinbutton').length).toBeGreaterThanOrEqual(2);
    unmount();
    renderControls(1, { _stretch: 'minmax' });
    expect(screen.queryAllByRole('spinbutton')).toHaveLength(0);
  });

  it('commits a valid low bound on blur', () => {
    const { onPaintProp } = renderControls(1, { _stretch: 'percentile' });
    const pmin = screen.getAllByRole('spinbutton')[0];
    // fix(#438) BLD-03: the inputs clamp on blur, not on every keystroke.
    fireEvent.change(pmin, { target: { value: '10' } });
    fireEvent.blur(pmin);
    expect(onPaintProp).toHaveBeenCalledWith('_pmin', 10);
  });

  it('never emits an out-of-range low bound', () => {
    const { onPaintProp } = renderControls(1, { _stretch: 'percentile' });
    const pmin = screen.getAllByRole('spinbutton')[0];
    for (const bad of ['99', '-5']) {
      fireEvent.change(pmin, { target: { value: bad } });
      fireEvent.blur(pmin);
    }
    expect(onPaintProp.mock.calls.filter(([k, v]) => k === '_pmin' && (v === 99 || v === -5))).toHaveLength(0);
  });

  // fix(#1778): the pmin/pmax Label had no htmlFor and the sibling <input>
  // had no id, so both percentile bounds announced as unnamed spin buttons.
  // This surface never appears in the gating axe suite: it only renders for
  // raster layers, and the suite's seeded layer is vector.
  it('names the low and high percentile bound inputs from their visible labels (#1778)', () => {
    renderControls(1, { _stretch: 'percentile' });

    expect(screen.getByLabelText('Low %')).toBeInTheDocument();
    expect(screen.getByLabelText('High %')).toBeInTheDocument();
  });
});

describe('RasterStretchControls — sigma', () => {
  it('marks the default sigma of 2 as pressed', () => {
    renderControls(1, { _stretch: 'stddev' });
    expect(screen.getByRole('button', { name: '2' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '1' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: '3' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('emits _sigma on click and renders no sigma buttons for minmax', () => {
    const { onPaintProp, unmount } = renderControls(1, { _stretch: 'stddev' });
    fireEvent.click(screen.getByRole('button', { name: '3' }));
    expect(onPaintProp).toHaveBeenCalledWith('_sigma', 3);
    unmount();
    renderControls(1, { _stretch: 'minmax' });
    expect(screen.queryByRole('button', { name: '3' })).not.toBeInTheDocument();
  });
});

describe('RasterStretchControls — colormap hint', () => {
  const hint = /Stretch sets the input range for the colormap/;

  it('shows for a single-band non-minmax stretch with a non-gray colormap', () => {
    renderControls(1, { _stretch: 'percentile', _colormap: 'viridis' });
    expect(screen.getByText(hint)).toBeInTheDocument();
  });

  it('stays hidden for minmax, for gray, and for multi-band', () => {
    const { unmount } = renderControls(1, { _stretch: 'minmax', _colormap: 'viridis' });
    expect(screen.queryByText(hint)).not.toBeInTheDocument();
    unmount();
    const second = renderControls(1, { _stretch: 'percentile', _colormap: 'gray' });
    expect(screen.queryByText(hint)).not.toBeInTheDocument();
    second.unmount();
    renderControls(3, { _stretch: 'percentile', _colormap: 'viridis' });
    expect(screen.queryByText(hint)).not.toBeInTheDocument();
  });
});
