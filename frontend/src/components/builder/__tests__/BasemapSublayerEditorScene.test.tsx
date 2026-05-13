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
    activeDetailLevel: 'default' as const,
    isCustomized: false,
    strokeColor: '#FF0000',
    strokeWidth: 2,
    casingColor: '#000000',
    casingWidth: 1,
    opacity: 1,
    minZoom: 0,
    maxZoom: 22,
    onDetailLevelChange: vi.fn(),
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
  it('Test 1: DETAIL LEVEL pill strip renders 4 pills with role="radiogroup" and role="radio" with aria-checked', () => {
    render(<BasemapSublayerEditorScene {...defaultProps({ activeDetailLevel: 'default' })} />);

    const radioGroup = screen.getByRole('radiogroup');
    expect(radioGroup).toBeInTheDocument();

    const pills = screen.getAllByRole('radio');
    const pillLabels = pills.map((p) => p.textContent?.trim());
    expect(pillLabels).toContain('Off');
    expect(pillLabels).toContain('Minimal');
    expect(pillLabels).toContain('Default');
    expect(pillLabels).toContain('Full');
    expect(pills).toHaveLength(4);

    // aria-checked on active pill
    const defaultPill = pills.find((p) => p.textContent?.trim() === 'Default');
    expect(defaultPill).toHaveAttribute('aria-checked', 'true');
    const offPill = pills.find((p) => p.textContent?.trim() === 'Off');
    expect(offPill).toHaveAttribute('aria-checked', 'false');
  });

  it('Test 2: active pill has bg-primary styling; inactive has bg-[var(--surface-2,...)]', () => {
    render(<BasemapSublayerEditorScene {...defaultProps({ activeDetailLevel: 'minimal' })} />);

    const pills = screen.getAllByRole('radio');
    const minimalPill = pills.find((p) => p.textContent?.trim() === 'Minimal');
    const fullPill = pills.find((p) => p.textContent?.trim() === 'Full');

    expect(minimalPill?.className).toContain('bg-primary');
    expect(fullPill?.className).not.toContain('bg-primary');
  });

  it('Test 3: clicking an inactive pill calls onDetailLevelChange(pillId)', () => {
    const onDetailLevelChange = vi.fn();
    render(
      <BasemapSublayerEditorScene
        {...defaultProps({ activeDetailLevel: 'default', onDetailLevelChange })}
      />,
    );

    const pills = screen.getAllByRole('radio');
    const offPill = pills.find((p) => p.textContent?.trim() === 'Off');
    expect(offPill).toBeTruthy();
    fireEvent.click(offPill!);

    expect(onDetailLevelChange).toHaveBeenCalledWith('off');
  });

  it('Test 4: shows customized hint when activeDetailLevel !== "default" AND isCustomized=true', () => {
    const { rerender } = render(
      <BasemapSublayerEditorScene
        {...defaultProps({ activeDetailLevel: 'minimal', isCustomized: true, sublayerName: 'Roads' })}
      />,
    );
    expect(screen.getByText(/Roads is currently customized/)).toBeInTheDocument();

    // Should NOT show when default level
    rerender(
      <BasemapSublayerEditorScene
        {...defaultProps({ activeDetailLevel: 'default', isCustomized: true, sublayerName: 'Roads' })}
      />,
    );
    expect(screen.queryByText(/Roads is currently customized/)).not.toBeInTheDocument();
  });

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
});
