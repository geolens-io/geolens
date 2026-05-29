import { fireEvent, render, screen } from '@/test/test-utils';
import { FillPatternPicker } from '../FillPatternPicker';
import { FILL_PATTERN_IDS } from '../layer-adapters/fill-pattern-images';

// Minimal t() function providing labels for all keys the picker uses
function makeT(extras: Record<string, string> = {}) {
  return (key: string): string => {
    const labels: Record<string, string> = {
      'style.fillPattern': 'Fill Pattern',
      'style.fillPatternNone': 'None',
      'style.fillPatternName.hatch': 'Hatch',
      'style.fillPatternName.crosshatch': 'Cross-hatch',
      'style.fillPatternName.diagonal': 'Diagonal',
      'style.fillPatternName.dots': 'Dots',
      'style.fillPatternName.grid': 'Grid',
      ...extras,
    };
    return labels[key] ?? key;
  };
}

describe('FillPatternPicker', () => {
  it('renders a "None" swatch plus one swatch per FILL_PATTERN_IDS (count = ids.length + 1)', () => {
    render(<FillPatternPicker value={undefined} onChange={vi.fn()} t={makeT()} />);
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(FILL_PATTERN_IDS.length + 1);
  });

  it('with value=undefined, the "None" swatch carries the selection-ring classes', () => {
    render(<FillPatternPicker value={undefined} onChange={vi.fn()} t={makeT()} />);
    const noneBtn = screen.getByRole('button', { name: 'None' });
    expect(noneBtn.className).toContain('border-primary');
    expect(noneBtn.className).toContain('ring-1');
  });

  it('with value=geolens-fill-hatch, the hatch swatch carries the selection-ring classes', () => {
    render(<FillPatternPicker value="geolens-fill-hatch" onChange={vi.fn()} t={makeT()} />);
    const hatchBtn = screen.getByRole('button', { name: 'Hatch' });
    expect(hatchBtn.className).toContain('border-primary');
    expect(hatchBtn.className).toContain('ring-1');
  });

  it('with value=geolens-fill-hatch, the "None" swatch does NOT carry the selection-ring', () => {
    render(<FillPatternPicker value="geolens-fill-hatch" onChange={vi.fn()} t={makeT()} />);
    const noneBtn = screen.getByRole('button', { name: 'None' });
    expect(noneBtn.className).not.toContain('border-primary');
    expect(noneBtn.className).not.toContain('ring-1');
  });

  it('clicking a pattern swatch fires onChange with that id', () => {
    const onChange = vi.fn();
    render(<FillPatternPicker value={undefined} onChange={onChange} t={makeT()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Hatch' }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('geolens-fill-hatch');
  });

  it('clicking "None" swatch fires onChange(undefined)', () => {
    const onChange = vi.fn();
    render(<FillPatternPicker value="geolens-fill-hatch" onChange={onChange} t={makeT()} />);
    fireEvent.click(screen.getByRole('button', { name: 'None' }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(undefined);
  });

  it('clicking each pattern swatch fires onChange with the correct id', () => {
    const onChange = vi.fn();
    render(<FillPatternPicker value={undefined} onChange={onChange} t={makeT()} />);
    const labelMap: Record<string, string> = {
      'geolens-fill-hatch': 'Hatch',
      'geolens-fill-crosshatch': 'Cross-hatch',
      'geolens-fill-diagonal': 'Diagonal',
      'geolens-fill-dots': 'Dots',
      'geolens-fill-grid': 'Grid',
    };
    for (const id of FILL_PATTERN_IDS) {
      onChange.mockClear();
      fireEvent.click(screen.getByRole('button', { name: labelMap[id] }));
      expect(onChange).toHaveBeenCalledWith(id);
    }
  });

  it('swatch aria-labels resolve through t (no raw key leakage)', () => {
    render(<FillPatternPicker value={undefined} onChange={vi.fn()} t={makeT()} />);
    // "None" should appear as the label text, not 'style.fillPatternNone'
    expect(screen.queryByRole('button', { name: 'style.fillPatternNone' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'None' })).toBeInTheDocument();
    // Pattern names should appear as labels, not raw i18n keys
    expect(screen.queryByRole('button', { name: 'style.fillPatternName.hatch' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hatch' })).toBeInTheDocument();
  });

  it('renders the section label via t("style.fillPattern")', () => {
    render(<FillPatternPicker value={undefined} onChange={vi.fn()} t={makeT()} />);
    expect(screen.getByText('Fill Pattern')).toBeInTheDocument();
  });
});
