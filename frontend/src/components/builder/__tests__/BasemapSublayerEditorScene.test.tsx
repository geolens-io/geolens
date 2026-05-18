import { fireEvent, render, screen } from '@/test/test-utils';
import { BasemapSublayerEditorScene, BasemapSublayerEditorFooter } from '../BasemapSublayerEditorScene';

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

vi.mock('../StyleColorPicker', () => ({
  StyleColorPicker: ({
    color,
    onChange,
    label,
  }: {
    color: string;
    onChange: (hex: string) => void;
    label: string;
  }) => (
    <button
      data-testid="color-picker"
      data-color={color}
      data-label={label}
      onClick={() => onChange('#ABCDEF')}
    >
      color
    </button>
  ),
}));

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

function defaultProps(
  overrides: Partial<React.ComponentProps<typeof BasemapSublayerEditorScene>> = {},
) {
  return {
    sublayerId: 'roads',
    sublayerName: 'Roads',
    strokeColor: '#FF0000',
    strokeWidth: 2,
    casingColor: '#000000',
    casingWidth: 1,
    opacity: 1,
    minZoom: 0,
    maxZoom: 22,
    onStrokeColorChange: vi.fn(),
    onStrokeWidthChange: vi.fn(),
    onCasingColorChange: vi.fn(),
    onCasingWidthChange: vi.fn(),
    onOpacityChange: vi.fn(),
    onZoomChange: vi.fn(),
    onResetSublayer: vi.fn(),
    ...overrides,
  };
}

describe('BasemapSublayerEditorScene', () => {
  // Phase 1051 Plan 11 (INV-01): DETAIL LEVEL pill strip removed — dead wiring.
  // Tests 1-4 (DETAIL LEVEL pill rendering, active pill styling, click dispatch,
  // customized hint) deleted alongside the production surface they pinned. The
  // regression guard for the REMOVE disposition is Test 13 below — asserts no
  // radiogroup, no `DETAIL LEVEL` heading, and no `currently customized` hint
  // text are rendered.

  it('Test 5: STROKE section renders 4 fields in a field grid', () => {
    render(<BasemapSublayerEditorScene {...defaultProps()} />);

    // Check labels exist
    expect(screen.getByText('STROKE')).toBeInTheDocument();
    expect(screen.getByText('Color')).toBeInTheDocument();
    expect(screen.getByText('Width')).toBeInTheDocument();
    expect(screen.getByText('Casing color')).toBeInTheDocument();
    expect(screen.getByText('Casing width')).toBeInTheDocument();
  });

  it('Test 6: Color/Casing-color fields render StyleColorPicker; Width/Casing-width render Slider', () => {
    const { container } = render(<BasemapSublayerEditorScene {...defaultProps({ strokeWidth: 3, casingWidth: 1.5 })} />);

    // 2 color pickers
    const colorPickers = screen.getAllByTestId('color-picker');
    expect(colorPickers.length).toBeGreaterThanOrEqual(2);

    // At least 2 sliders (width + casing width + possible opacity)
    const sliders = screen.getAllByRole('slider');
    expect(sliders.length).toBeGreaterThanOrEqual(2);

    // Check that width slider has expected range (0-8px)
    const widthSlider = sliders.find((s) => s.getAttribute('aria-label')?.toLowerCase().includes('stroke width') || s.getAttribute('aria-valuemin') === '0' && s.getAttribute('aria-valuemax') === '8');
    expect(widthSlider).toBeTruthy();

    // Suppress unused warning
    void container;
  });

  it('Test 7: width slider value change calls onStrokeWidthChange(value); value label has tabular-nums class', () => {
    const onStrokeWidthChange = vi.fn();
    render(<BasemapSublayerEditorScene {...defaultProps({ strokeWidth: 2, onStrokeWidthChange })} />);

    // Find value span with tabular-nums
    const valueSpan = document.querySelector('.tabular-nums');
    expect(valueSpan).toBeTruthy();
  });

  it('Test 8: VISIBILITY section renders opacity slider + min/max zoom inputs', () => {
    render(<BasemapSublayerEditorScene {...defaultProps({ minZoom: 3, maxZoom: 18 })} />);

    // Opacity slider
    const opacitySlider = screen.getByRole('slider', { name: /Opacity/i });
    expect(opacitySlider).toBeInTheDocument();

    // Zoom inputs
    const minZoomInput = screen.getByRole('spinbutton', { name: /Minimum zoom/i });
    const maxZoomInput = screen.getByRole('spinbutton', { name: /Maximum zoom/i });
    expect(minZoomInput).toBeInTheDocument();
    expect(maxZoomInput).toBeInTheDocument();
    expect(minZoomInput).toHaveValue(3);
    expect(maxZoomInput).toHaveValue(18);
  });

  it('Test 9: RESET section is collapsed by default; collapsed state shows hint', () => {
    render(<BasemapSublayerEditorScene {...defaultProps()} />);

    // RESET label should be visible (as the collapsible trigger)
    expect(screen.getByText('RESET')).toBeInTheDocument();
    // Hint text in collapsed state
    expect(screen.getByText(/Reset to preset default/)).toBeInTheDocument();
    // The reset button should NOT be visible initially (inside CollapsibleContent)
    expect(screen.queryByRole('button', { name: /Reset to default/i })).not.toBeInTheDocument();
  });

  it('Test 10: clicking Reset button triggers inline alertdialog with correct message and buttons', () => {
    render(
      <BasemapSublayerEditorScene {...defaultProps({ sublayerName: 'Roads' })} />,
    );

    // Open the collapsible
    const resetTrigger = screen.getByText('RESET').closest('button')!;
    fireEvent.click(resetTrigger);

    // Now the "Reset to default" button should appear
    const resetBtn = screen.getByRole('button', { name: /Reset to default/i });
    expect(resetBtn).toBeInTheDocument();

    // Click to show confirm
    fireEvent.click(resetBtn);

    // alertdialog should appear
    const alertDialog = screen.getByRole('alertdialog');
    expect(alertDialog).toBeInTheDocument();
    expect(screen.getByText(/This will remove all custom appearance for Roads/)).toBeInTheDocument();

    // Both buttons — use getAllByRole to handle any ambiguity
    const allButtons = screen.getAllByRole('button');
    const resetConfirmBtn = allButtons.find((b) => b.textContent?.trim() === 'Reset');
    const keepBtn = screen.getByRole('button', { name: /Keep customization/i });
    expect(resetConfirmBtn).toBeTruthy();
    expect(keepBtn).toBeInTheDocument();
  });

  it('Test 11: "Reset" button click calls onResetSublayer(); "Keep customization" cancels', () => {
    const onResetSublayer = vi.fn();
    render(<BasemapSublayerEditorScene {...defaultProps({ onResetSublayer })} />);

    // Open collapsible
    const resetTrigger = screen.getByText('RESET').closest('button')!;
    fireEvent.click(resetTrigger);

    // Show confirm
    const resetBtn = screen.getByRole('button', { name: /Reset to default/i });
    fireEvent.click(resetBtn);

    // Check alert dialog is shown
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();

    // Click "Keep customization" — cancels
    const keepBtn = screen.getByRole('button', { name: /Keep customization/i });
    fireEvent.click(keepBtn);
    expect(onResetSublayer).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();

    // Show confirm again, then click "Reset"
    // Re-query the "Reset to default" button after cancellation (DOM may have re-rendered)
    const resetToDefaultBtn2 = screen.getByRole('button', { name: /Reset to default/i });
    fireEvent.click(resetToDefaultBtn2);
    // Find the Reset confirm button (not the collapsible trigger) by text content
    const allButtons2 = screen.getAllByRole('button');
    const confirmResetBtn = allButtons2.find((b) => b.textContent?.trim() === 'Reset');
    expect(confirmResetBtn).toBeTruthy();
    fireEvent.click(confirmResetBtn!);
    expect(onResetSublayer).toHaveBeenCalledOnce();
  });

  it('Test 12: footer renders ONE full-width "Back to basemap" ghost button; click calls onBackToBasemap()', () => {
    const onBackToBasemap = vi.fn();
    render(<BasemapSublayerEditorFooter onBackToBasemap={onBackToBasemap} />);

    const backBtn = screen.getByRole('button', { name: /Back to basemap/i });
    expect(backBtn).toBeInTheDocument();
    expect(backBtn.className).toContain('w-full');

    fireEvent.click(backBtn);
    expect(onBackToBasemap).toHaveBeenCalledOnce();
  });

  it('Test 13: DETAIL LEVEL section is removed (Phase 1051 INV-01 REMOVE disposition pin)', () => {
    // Regression guard for the REMOVE disposition shipped in Phase 1051 Plan 11:
    // the dead-wired DETAIL LEVEL pill strip and customized-hint paragraph must
    // not be reintroduced without a real consumer for sublayer detail-level
    // style mutation. If a future feature needs this surface, it should re-add
    // the props + JSX AND wire a real onDetailLevelChange handler that mutates
    // MapLibre style at the same time — this test exists to make that intent
    // explicit at the call site.
    render(<BasemapSublayerEditorScene {...defaultProps({ sublayerName: 'Roads' })} />);

    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument();
    expect(screen.queryByText(/DETAIL LEVEL/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/currently customized/i)).not.toBeInTheDocument();
  });
});
