import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@/test/test-utils';
import { AdvancedJsonEditor } from '../AdvancedJsonEditor';

/**
 * fix(#916): symbol mode keeps the layer's circle paint (renderAs.ts swaps only
 * heatmap's paint object), but the editor validated BOTH blocks against the
 * resolved 'symbol' type. Every stored circle-* key was rejected, so an
 * edit-free Apply on the Paint block always errored and the block was a dead
 * end for the whole mode. The Paint block now validates as 'circle' while the
 * Layout block stays on 'symbol' so symbol-only layout keys remain authorable.
 */

function openBlock(name: RegExp) {
  fireEvent.click(screen.getByRole('button', { name }));
}

function renderEditor(overrides: Partial<Parameters<typeof AdvancedJsonEditor>[0]> = {}) {
  const onPaintChange = vi.fn();
  const onLayoutChange = vi.fn();
  render(
    <AdvancedJsonEditor
      paint={{ 'circle-color': '#ff0000', 'circle-radius': 5 }}
      layout={{}}
      onPaintChange={onPaintChange}
      onLayoutChange={onLayoutChange}
      defaultOpen
      layerType="symbol"
      {...overrides}
    />,
  );
  return { onPaintChange, onLayoutChange };
}

describe('AdvancedJsonEditor — symbol mode validates each block against what it holds', () => {
  it('applies the stored circle paint unchanged instead of rejecting every key', () => {
    const { onPaintChange } = renderEditor();
    openBlock(/paint/i);
    fireEvent.click(screen.getByRole('button', { name: /apply/i }));

    expect(onPaintChange).toHaveBeenCalledWith({ 'circle-color': '#ff0000', 'circle-radius': 5 });
    expect(screen.queryByText(/unknown property/i)).not.toBeInTheDocument();
  });

  it('still rejects an invalid circle value in the Paint block', () => {
    const { onPaintChange } = renderEditor();
    openBlock(/paint/i);
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: JSON.stringify({ 'circle-radius': 'not-a-number' }) },
    });
    fireEvent.click(screen.getByRole('button', { name: /apply/i }));

    expect(onPaintChange).not.toHaveBeenCalled();
    // The textarea also contains the key, so match the error node specifically.
    expect(screen.getAllByText(/circle-radius/).some((el) => el.className.includes('text-destructive'))).toBe(true);
  });

  it('keeps symbol-only layout keys authorable in the Layout block', () => {
    const { onLayoutChange } = renderEditor();
    openBlock(/layout/i);
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: JSON.stringify({ 'icon-image': 'marker', 'symbol-placement': 'line' }) },
    });
    fireEvent.click(screen.getByRole('button', { name: /apply/i }));

    expect(onLayoutChange).toHaveBeenCalledWith({ 'icon-image': 'marker', 'symbol-placement': 'line' });
  });

  it('leaves non-symbol layer types on a single resolved type', () => {
    const { onPaintChange } = renderEditor({ layerType: 'circle' });
    openBlock(/paint/i);
    fireEvent.click(screen.getByRole('button', { name: /apply/i }));
    expect(onPaintChange).toHaveBeenCalled();
  });
});
