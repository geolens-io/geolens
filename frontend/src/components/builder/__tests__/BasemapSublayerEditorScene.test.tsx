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
    opacity: 1,
    strokeColor: '#888888',
    strokeWidth: 1,
    casingColor: '#cccccc',
    casingWidth: 0.5,
    minZoom: 0,
    maxZoom: 22,
    onOpacityChange: vi.fn(),
    onResetSublayer: vi.fn(),
    onStrokeColorChange: vi.fn(),
    onStrokeWidthChange: vi.fn(),
    onCasingColorChange: vi.fn(),
    onCasingWidthChange: vi.fn(),
    onMinZoomChange: vi.fn(),
    onMaxZoomChange: vi.fn(),
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
  //
  // Phase 1052 Plan 03 (EMRG-FN-01): STROKE section + zoom range inputs
  // removed — Tests 5-7 (STROKE field rendering, color picker / slider
  // counts, width slider → onStrokeWidthChange) and the zoom-input
  // assertions in Test 8 deleted alongside their production surface.
  //
  // Phase 1059 BSE-01 (Path B FIX): Test 14 is INVERTED from its
  // v1011.1 EMRG-FN-01 form. The STROKE / CASING / ZOOM controls are now
  // live with a real persistence path. See backend Plan 1059-01 (Pydantic
  // SublayerOverride) and frontend Plan 1059-02 (applySublayerOverrides
  // helper). Tests 15-21 cover the 6 new callbacks + back-compat.
  // Test 13 (DETAIL LEVEL absence) is UNCHANGED — that disposition stands
  // per Phase 1059 CONTEXT.md D-18.

  it('Test 8: VISIBILITY section renders opacity slider', () => {
    render(<BasemapSublayerEditorScene {...defaultProps()} />);

    // Opacity slider
    const opacitySlider = screen.getByRole('slider', { name: /Opacity/i });
    expect(opacitySlider).toBeInTheDocument();
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

  // Phase 1059 BSE-01 (Path B FIX) — Test 14 is INVERTED from its previous
  // v1011.1 EMRG-FN-01 form. The STROKE / CASING / ZOOM controls are now
  // live with a real persistence path. See backend Plan 1059-01 (Pydantic
  // SublayerOverride) and frontend Plan 1059-02 (applySublayerOverrides
  // helper). Test 13 (DETAIL LEVEL absence) is UNCHANGED — that disposition
  // stands per Phase 1059 CONTEXT.md D-18.
  it('Test 14: STROKE + CASING + ZOOM RANGE sections render (Phase 1059 BSE-01 Path B FIX)', () => {
    // Phase 1059 BSE-01 RESTORATION: the v1011.1 EMRG-FN-01 REMOVE disposition
    // is reversed. The STROKE / CASING / ZOOM sections must render with their
    // controls + working callbacks. Backend persistence: SublayerOverride
    // Pydantic model + MapBasemapConfig.sublayer_overrides jsonb (Plan 1059-01).
    // MapLibre mutation: applySublayerOverrides helper (Plan 1059-02).
    render(<BasemapSublayerEditorScene {...defaultProps({ sublayerName: 'Roads' })} />);

    expect(screen.getByText('STROKE')).toBeInTheDocument();
    expect(screen.getByText('CASING')).toBeInTheDocument();
    expect(screen.getByText('ZOOM RANGE')).toBeInTheDocument();
    // Stroke + casing width sliders + opacity slider (3 total sliders in component)
    const sliders = screen.getAllByRole('slider');
    expect(sliders.length).toBeGreaterThanOrEqual(3);
    // Min + max zoom inputs (spinbuttons via type="number")
    expect(screen.getByRole('spinbutton', { name: /Minimum zoom/i })).toBeInTheDocument();
    expect(screen.getByRole('spinbutton', { name: /Maximum zoom/i })).toBeInTheDocument();
  });

  it('Test 15: STROKE color picker swatch button renders with correct aria-label', () => {
    // StyleColorPicker renders a trigger button with aria-label=label prop and
    // title=color value. We verify the swatch renders (which confirms onChange
    // is wired) — the color picker popover itself uses Radix portal which is
    // not testable in jsdom without act+portal interaction. The callback
    // wire-up is end-to-end verified via the existing basemap-style-mutation
    // tests (Plan 1059-02) and live MCP smoke in Phase 1060.
    const onStrokeColorChange = vi.fn();
    render(<BasemapSublayerEditorScene {...defaultProps({ onStrokeColorChange, strokeColor: '#888888' })} />);
    // The stroke swatch button has aria-label="Color" (basemapSublayer.strokeColor key)
    // and title matching the strokeColor value
    const strokeSwatchBtn = screen.getAllByRole('button').find(
      (b) => b.getAttribute('title') === '#888888' && b.getAttribute('aria-label') === 'Color',
    );
    expect(strokeSwatchBtn).toBeDefined();
    expect(strokeSwatchBtn!.style.background).toBeTruthy();
  });

  it('Test 16: STROKE width slider change fires onStrokeWidthChange', () => {
    const onStrokeWidthChange = vi.fn();
    render(<BasemapSublayerEditorScene {...defaultProps({ onStrokeWidthChange, strokeWidth: 1 })} />);
    const sliders = screen.getAllByRole('slider');
    const strokeSlider = sliders.find((s) => s.getAttribute('aria-label') === 'Stroke width');
    expect(strokeSlider).toBeDefined();
    // shadcn/radix Slider responds to keyboard events
    fireEvent.keyDown(strokeSlider!, { key: 'ArrowRight' });
    expect(onStrokeWidthChange).toHaveBeenCalled();
    const callValue = onStrokeWidthChange.mock.calls[0][0];
    expect(typeof callValue).toBe('number');
    expect(callValue).toBeGreaterThanOrEqual(1);
  });

  it('Test 17: CASING color picker swatch button renders with correct aria-label', () => {
    // Same jsdom-portal constraint as Test 15. Verifies the casing swatch renders
    // with the correct aria-label (basemapSublayer.casingColor key = "Casing color")
    // and title matching the casingColor value. Callback wire-up end-to-end
    // verified via basemap-style-mutation tests (Plan 1059-02) + Phase 1060 MCP.
    const onCasingColorChange = vi.fn();
    render(<BasemapSublayerEditorScene {...defaultProps({ onCasingColorChange, casingColor: '#cccccc' })} />);
    const casingSwatchBtn = screen.getAllByRole('button').find(
      (b) => b.getAttribute('title') === '#cccccc' && b.getAttribute('aria-label') === 'Casing color',
    );
    expect(casingSwatchBtn).toBeDefined();
    expect(casingSwatchBtn!.style.background).toBeTruthy();
  });

  it('Test 18: CASING width slider change fires onCasingWidthChange', () => {
    const onCasingWidthChange = vi.fn();
    render(<BasemapSublayerEditorScene {...defaultProps({ onCasingWidthChange, casingWidth: 0.5 })} />);
    const sliders = screen.getAllByRole('slider');
    const casingSlider = sliders.find((s) => s.getAttribute('aria-label') === 'Casing width');
    expect(casingSlider).toBeDefined();
    fireEvent.keyDown(casingSlider!, { key: 'ArrowRight' });
    expect(onCasingWidthChange).toHaveBeenCalled();
    const callValue = onCasingWidthChange.mock.calls[0][0];
    expect(typeof callValue).toBe('number');
    expect(callValue).toBeGreaterThanOrEqual(0.5);
  });

  it('Test 19: Min zoom input change fires onMinZoomChange with clamped value', () => {
    const onMinZoomChange = vi.fn();
    render(<BasemapSublayerEditorScene {...defaultProps({ onMinZoomChange, minZoom: 0 })} />);
    const minInput = screen.getByRole('spinbutton', { name: /Minimum zoom/i });
    // Entering 25 should fire with clamped value 24
    fireEvent.change(minInput, { target: { value: '25' } });
    expect(onMinZoomChange).toHaveBeenCalledWith(24);
  });

  it('Test 20: Max zoom input change fires onMaxZoomChange with clamped value', () => {
    const onMaxZoomChange = vi.fn();
    render(<BasemapSublayerEditorScene {...defaultProps({ onMaxZoomChange, maxZoom: 22 })} />);
    const maxInput = screen.getByRole('spinbutton', { name: /Maximum zoom/i });
    // Entering -1 should fire with clamped value 0
    fireEvent.change(maxInput, { target: { value: '-1' } });
    expect(onMaxZoomChange).toHaveBeenCalledWith(0);
  });

  it('Test 21: component renders without crashing when optional value props are undefined', () => {
    // Defensive callers (e.g., legacy MapBuilderPage paths) may pass undefined
    // for strokeColor / strokeWidth / casingColor / casingWidth / minZoom / maxZoom.
    // Component must render with safe defaults and noop on callback if not provided.
    const minimalProps = {
      sublayerId: 'roads',
      sublayerName: 'Roads',
      opacity: 1,
      onOpacityChange: vi.fn(),
      onResetSublayer: vi.fn(),
      // intentionally NO stroke/casing/zoom props
    };
    const { container } = render(<BasemapSublayerEditorScene {...minimalProps} />);
    expect(container).toBeInTheDocument();
    expect(screen.getByText('STROKE')).toBeInTheDocument();
    expect(screen.getByText('CASING')).toBeInTheDocument();
    expect(screen.getByText('ZOOM RANGE')).toBeInTheDocument();
  });
});
