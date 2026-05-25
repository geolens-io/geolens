import { fireEvent, render, screen } from '@/test/test-utils';
import { SettingsEditorScene } from '../SettingsEditorScene';
import type { SettingsEditorSceneProps } from '../SettingsEditorScene';

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

vi.mock('@/components/ui/slider', () => ({
  Slider: ({
    value,
    min,
    max,
    step,
    onValueChange,
    'aria-label': ariaLabel,
    'aria-valuetext': ariaValuetext,
    disabled,
    'aria-disabled': ariaDisabled,
  }: {
    value: number[];
    min: number;
    max: number;
    step: number;
    onValueChange: (value: number[]) => void;
    'aria-label': string;
    'aria-valuetext': string;
    disabled?: boolean;
    'aria-disabled'?: boolean;
  }) => (
    <input
      type="range"
      aria-label={ariaLabel}
      aria-valuetext={ariaValuetext}
      value={value[0]}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      aria-disabled={ariaDisabled}
      onChange={(e) => onValueChange([Number(e.currentTarget.value)])}
    />
  ),
}));

vi.mock('@/components/ui/switch', () => ({
  Switch: ({
    checked,
    onCheckedChange,
    'aria-label': ariaLabel,
  }: {
    checked: boolean;
    onCheckedChange: (checked: boolean) => void;
    'aria-label': string;
  }) => (
    <input
      type="checkbox"
      role="switch"
      aria-label={ariaLabel}
      checked={checked}
      onChange={(e) => onCheckedChange(e.currentTarget.checked)}
    />
  ),
}));

vi.mock('@/components/map-widgets/registry', () => ({
  getWidgets: () => [
    { id: 'measurement', labelKey: 'widgets.measurement.label', icon: () => null },
    { id: 'legend', labelKey: 'widgets.legend.label', icon: () => null },
  ],
}));

vi.mock('../StyleColorPicker', () => ({
  StyleColorPicker: ({
    label,
    color,
    onChange,
  }: {
    label: string;
    color: string;
    onChange: (hex: string) => void;
  }) => (
    <button
      type="button"
      aria-label={label}
      title={color}
      onClick={() => onChange('#123456')}
    />
  ),
}));

function defaultProps(overrides: Partial<SettingsEditorSceneProps> = {}): SettingsEditorSceneProps {
  return {
    terrainConfig: null,
    isTerrainActive: false,
    boundLayerName: undefined,
    onExaggerationChange: vi.fn(),
    activeWidgetIds: new Set<string>(),
    onToggleWidget: vi.fn(),
    backgroundColor: null,
    onBackgroundColorChange: vi.fn(),
    onBackgroundColorReset: vi.fn(),
    projection: 'mercator',
    onSetProjection: vi.fn(),
    ...overrides,
  };
}

describe('SettingsEditorScene', () => {
  // Test 1: Renders all four sections expanded by default
  it('renders all four sections expanded by default', () => {
    render(<SettingsEditorScene {...defaultProps()} />);

    expect(screen.getByText('APPEARANCE')).toBeInTheDocument();
    expect(screen.getByText('TERRAIN')).toBeInTheDocument();
    expect(screen.getByText('WIDGETS')).toBeInTheDocument();
    expect(screen.getByText('PROJECTION')).toBeInTheDocument();

    expect(screen.getByRole('button', { name: 'Background' })).toHaveAttribute('title', '#ffffff');

    // Widget rows visible (all sections expanded)
    // The t() mock resolves labelKey with defaultValue=widget.id, so labels render as the widget id
    expect(screen.getByText('measurement')).toBeInTheDocument();
    expect(screen.getByText('legend')).toBeInTheDocument();

    // Projection pills visible
    expect(screen.getByRole('radio', { name: 'Mercator' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Globe' })).toBeInTheDocument();
  });

  // Test 2: Terrain disabled when not active
  it('terrain section disabled when isTerrainActive=false', () => {
    render(<SettingsEditorScene {...defaultProps({ isTerrainActive: false })} />);

    const slider = screen.getByLabelText(/Terrain exaggeration/i);
    expect(slider).toBeDisabled();

    expect(screen.getByText(/No terrain layer is active/i)).toBeInTheDocument();
  });

  // Test 3: Terrain active state
  it('terrain section enabled when isTerrainActive=true with bound layer hint', () => {
    render(
      <SettingsEditorScene
        {...defaultProps({
          isTerrainActive: true,
          terrainConfig: { enabled: true, exaggeration: 1.5, source_dataset_id: 'demo-dem' } as SettingsEditorSceneProps['terrainConfig'],
          boundLayerName: 'Demo DEM',
        })}
      />,
    );

    const slider = screen.getByLabelText(/Terrain exaggeration/i);
    expect(slider).not.toBeDisabled();

    expect(screen.getByText(/Bound to: Demo DEM/i)).toBeInTheDocument();
    expect(screen.queryByText(/No terrain layer is active/i)).not.toBeInTheDocument();
  });

  // Test 4: Exaggeration slider fires onExaggerationChange
  it('exaggeration slider calls onExaggerationChange with numeric value', () => {
    const onExaggerationChange = vi.fn();
    render(
      <SettingsEditorScene
        {...defaultProps({
          isTerrainActive: true,
          terrainConfig: { enabled: true, exaggeration: 1.0, source_dataset_id: 'demo' } as SettingsEditorSceneProps['terrainConfig'],
          onExaggerationChange,
        })}
      />,
    );

    const slider = screen.getByLabelText(/Terrain exaggeration/i);
    fireEvent.change(slider, { target: { value: '2.0' } });

    expect(onExaggerationChange).toHaveBeenCalledOnce();
    expect(onExaggerationChange).toHaveBeenCalledWith(2.0);
  });

  // Test 5: Widget toggles render with correct aria-label (UX-04: "Enable {name}" / "Disable {name}")
  it('widget toggle rows render with correct aria-label based on active state', () => {
    render(
      <SettingsEditorScene
        {...defaultProps({ activeWidgetIds: new Set(['legend']) })}
      />,
    );

    // The t() mock resolves labelKey with defaultValue=widget.id, so labels render as the widget id
    const measurementSwitch = screen.getByRole('switch', { name: 'Enable measurement' });
    expect(measurementSwitch).toBeInTheDocument();

    const legendSwitch = screen.getByRole('switch', { name: 'Disable legend' });
    expect(legendSwitch).toBeInTheDocument();
  });

  // Test 6: Clicking widget toggle calls onToggleWidget
  it('clicking widget toggle calls onToggleWidget with correct widgetId', () => {
    const onToggleWidget = vi.fn();
    render(
      <SettingsEditorScene
        {...defaultProps({ onToggleWidget })}
      />,
    );

    const measurementSwitch = screen.getByRole('switch', { name: 'Enable measurement' });
    fireEvent.click(measurementSwitch);

    expect(onToggleWidget).toHaveBeenCalledOnce();
    expect(onToggleWidget).toHaveBeenCalledWith('measurement');
  });

  // Test 7: Projection pill states — mercator active
  it('Mercator pill is active when projection=mercator; Globe pill is inactive; no disclaimer', () => {
    render(<SettingsEditorScene {...defaultProps({ projection: 'mercator' })} />);

    const mercatorPill = screen.getByRole('radio', { name: 'Mercator' });
    const globePill = screen.getByRole('radio', { name: 'Globe' });

    expect(mercatorPill).toHaveAttribute('aria-checked', 'true');
    expect(globePill).toHaveAttribute('aria-checked', 'false');

    expect(screen.queryByText(/Globe projection is experimental/i)).not.toBeInTheDocument();
  });

  // Test 8: Globe projection state — disclaimer shown
  it('Globe pill is active and disclaimer shown when projection=globe', () => {
    render(<SettingsEditorScene {...defaultProps({ projection: 'globe' })} />);

    const globePill = screen.getByRole('radio', { name: 'Globe' });
    expect(globePill).toHaveAttribute('aria-checked', 'true');

    expect(screen.getByText(/Globe projection is experimental/i)).toBeInTheDocument();
  });

  // Test 9: Clicking projection pill calls onSetProjection; clicking active pill does not
  it('clicking inactive projection pill calls onSetProjection; clicking active pill does not', () => {
    const onSetProjection = vi.fn();
    render(
      <SettingsEditorScene
        {...defaultProps({ projection: 'mercator', onSetProjection })}
      />,
    );

    // Click Globe (inactive) — should fire
    const globePill = screen.getByRole('radio', { name: 'Globe' });
    fireEvent.click(globePill);
    expect(onSetProjection).toHaveBeenCalledOnce();
    expect(onSetProjection).toHaveBeenCalledWith('globe');

    onSetProjection.mockClear();

    // Click Mercator (active) — should NOT fire
    const mercatorPill = screen.getByRole('radio', { name: 'Mercator' });
    fireEvent.click(mercatorPill);
    expect(onSetProjection).not.toHaveBeenCalled();
  });

  // Test 10: Background color picker and reset actions
  it('background color controls call their handlers', () => {
    const onBackgroundColorChange = vi.fn();
    const onBackgroundColorReset = vi.fn();
    render(
      <SettingsEditorScene
        {...defaultProps({
          backgroundColor: '#abcdef',
          onBackgroundColorChange,
          onBackgroundColorReset,
        })}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Background' }));
    expect(onBackgroundColorChange).toHaveBeenCalledWith('#123456');

    fireEvent.click(screen.getByRole('button', { name: 'Reset background color' }));
    expect(onBackgroundColorReset).toHaveBeenCalledOnce();
  });

  // Test 11: No footer Delete button
  it('has no footer delete button', () => {
    render(<SettingsEditorScene {...defaultProps()} />);
    expect(screen.queryByRole('button', { name: /delete/i })).toBeNull();
  });
});
