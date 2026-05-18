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
    opacity: 1,
    onOpacityChange: vi.fn(),
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
  //
  // Phase 1052 Plan 03 (EMRG-FN-01): STROKE section + zoom range inputs
  // removed — Tests 5-7 (STROKE field rendering, color picker / slider
  // counts, width slider → onStrokeWidthChange) and the zoom-input
  // assertions in Test 8 deleted alongside their production surface.
  // Test 14 below is the EMRG-FN-01 REMOVE-disposition regression pin
  // (positive-form queryBy* — mirrors Test 13's INV-01 pattern).

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

  it('Test 14: STROKE section + zoom range inputs are removed (Phase 1052 EMRG-FN-01 REMOVE disposition pin)', () => {
    // Regression guard for the REMOVE disposition shipped in Phase 1052 Plan 01:
    // the dead-stub STROKE section (color/width/casing color/casing width
    // controls) and VISIBILITY zoom range inputs (min/max) must not be
    // reintroduced without real consumers for sublayer style mutation. If
    // a future feature needs these surfaces, it should re-add the props +
    // JSX AND wire real onStrokeColorChange / onZoomChange handlers that
    // mutate MapLibre style at the same time — this test exists to make
    // that intent explicit at the call site.
    render(<BasemapSublayerEditorScene {...defaultProps({ sublayerName: 'Roads' })} />);

    expect(screen.queryByText(/^STROKE$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Stroke color$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Casing color$/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('spinbutton', { name: /Minimum zoom/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('spinbutton', { name: /Maximum zoom/i })).not.toBeInTheDocument();
  });
});
