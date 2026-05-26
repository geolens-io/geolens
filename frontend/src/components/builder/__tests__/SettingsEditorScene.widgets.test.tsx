import { fireEvent, render, screen } from '@/test/test-utils';
import { SettingsEditorScene } from '../SettingsEditorScene';
import type { SettingsEditorSceneProps } from '../SettingsEditorScene';

// Phase 1051 Plan 07 (UX-04): regression suite covering the refined
// Map Settings → Widgets section. The Switch row is the SINGLE source
// of truth for widget availability; on-map controls (e.g., MapToolbar
// Measure / Legend buttons) remain functional for live interaction but
// are NOT a duplicate of the availability toggle.
//
// New i18n keys exercised here:
//   - settings.enableWidget         → "Enable {{name}}"
//   - settings.disableWidget        → "Disable {{name}}"
//   - settings.widgetsAvailabilityNote → descriptive note paragraph

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
  StyleColorPicker: ({ label, color }: { label: string; color: string }) => (
    <button type="button" aria-label={label} title={color} />
  ),
}));

function defaultProps(overrides: Partial<SettingsEditorSceneProps> = {}): SettingsEditorSceneProps {
  return {
    terrainConfig: null,
    isTerrainActive: false,
    boundLayerName: undefined,
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

describe('SettingsEditorScene · Widgets section (UX-04)', () => {
  // Test 1 — disabled widget reads "Enable {name}"
  it('Switch aria-label reads "Enable {name}" when widget is OFF', () => {
    render(<SettingsEditorScene {...defaultProps({ activeWidgetIds: new Set<string>() })} />);

    // Both widgets are OFF — both should read "Enable {label}"
    expect(screen.getByRole('switch', { name: 'Enable measurement' })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Enable legend' })).toBeInTheDocument();
  });

  // Test 2 — enabled widget reads "Disable {name}"
  it('Switch aria-label reads "Disable {name}" when widget is ON', () => {
    render(
      <SettingsEditorScene
        {...defaultProps({ activeWidgetIds: new Set<string>(['legend']) })}
      />,
    );

    expect(screen.getByRole('switch', { name: 'Disable legend' })).toBeInTheDocument();
    // The other widget stays OFF
    expect(screen.getByRole('switch', { name: 'Enable measurement' })).toBeInTheDocument();
  });

  // Test 3 — toggling the Switch calls onToggleWidget with the correct id
  it('toggling a widget Switch calls onToggleWidget once with the widget id', () => {
    const onToggleWidget = vi.fn();
    render(
      <SettingsEditorScene
        {...defaultProps({ activeWidgetIds: new Set<string>(), onToggleWidget })}
      />,
    );

    const measurementSwitch = screen.getByRole('switch', { name: 'Enable measurement' });
    fireEvent.click(measurementSwitch);

    expect(onToggleWidget).toHaveBeenCalledOnce();
    expect(onToggleWidget).toHaveBeenCalledWith('measurement');
  });

  // Test 4 — descriptive note renders in the section
  it('renders the availability-note paragraph above the widget rows', () => {
    render(<SettingsEditorScene {...defaultProps()} />);

    expect(
      screen.getByText('Controls whether each widget appears on the map.'),
    ).toBeInTheDocument();
  });

  // Test 5 — single Switch per widget id (no duplicate availability controls)
  it('renders exactly one Switch element per widget id within the Settings scene', () => {
    render(<SettingsEditorScene {...defaultProps()} />);

    // 2 widgets in the mock registry, so exactly 2 Switches must exist
    const switches = screen.getAllByRole('switch');
    expect(switches).toHaveLength(2);

    // and none of them share an aria-label (no duplicate availability control for the same widget)
    const labels = switches.map((sw) => sw.getAttribute('aria-label'));
    expect(new Set(labels).size).toBe(labels.length);
  });
});
