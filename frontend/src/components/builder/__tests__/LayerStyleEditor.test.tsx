import { act, fireEvent, render, screen, within } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { LayerStyleEditor, hasUnsavedStyleChanges } from '../LayerStyleEditor';
import { LayerEditorPanel } from '../LayerEditorPanel';
import { stopsToLineGradientExpression } from '../LineGradientControls';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

// Radix Select uses ResizeObserver internally
(globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

const makeLayer = (overrides: Partial<MapLayerResponse> = {}): MapLayerResponse => ({
  id: 'layer-1',
  dataset_id: 'ds-1',
  dataset_name: 'test-dataset',
  dataset_geometry_type: 'LineString',
  dataset_table_name: 'test_table',
  dataset_extent_bbox: null,
  dataset_column_info: null,
  dataset_feature_count: null,
  dataset_sample_values: null,
  display_name: 'Test Layer',
  sort_order: 0,
  visible: true,
  opacity: 1,
  paint: { 'line-color': '#ff0000', 'line-width': 2 },
  layout: {},
  filter: null,
  label_config: null,
  style_config: null,
  ...overrides,
});

describe('LayerStyleEditor - SP-05 pending preview banner gating', () => {
  it('does NOT show the pending preview banner on first open with no savedLayer baseline', () => {
    // No savedLayer prop → draft is considered clean (no dirty tracking source).
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          opacity: 0.42,
          paint: { 'fill-color': '#123456', 'fill-opacity': 0.4, '_outline-color': '#abcdef' },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );
    expect(screen.queryByText('Pending style preview')).not.toBeInTheDocument();
  });

  it('does NOT show the pending preview banner when savedLayer matches the current draft', () => {
    const layer = makeLayer({
      dataset_geometry_type: 'Polygon',
      opacity: 0.42,
      paint: { 'fill-color': '#123456', 'fill-opacity': 0.4, '_outline-color': '#abcdef' },
    });
    render(
      <LayerStyleEditor
        layer={layer}
        savedLayer={layer}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );
    expect(screen.queryByText('Pending style preview')).not.toBeInTheDocument();
  });

  it('SHOWS the pending preview banner when draft paint diverges from savedLayer.paint', () => {
    const saved = makeLayer({
      dataset_geometry_type: 'Polygon',
      paint: { 'fill-color': '#123456', 'fill-opacity': 0.4 },
    });
    // Draft has a different fill-color — dirty.
    const draft = { ...saved, paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.4 } };
    render(
      <LayerStyleEditor
        layer={draft}
        savedLayer={saved}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );
    expect(screen.getByText('Pending style preview')).toBeInTheDocument();
    expect(screen.getByText('Reflects this layer before save')).toBeInTheDocument();
  });

  // fix(#461): the banner action ("Revert") restores the
  // server baseline; the section-header action ("Reset") clears to library
  // defaults. They are now distinct handlers, so assert each separately.
  it('banner Revert restores the saved baseline paint/layout/opacity (not defaults)', async () => {
    const onStyleConfigChange = vi.fn();
    const onOpacityChange = vi.fn();
    const onLayoutChange = vi.fn();
    const user = userEvent.setup();

    const saved = makeLayer({
      dataset_geometry_type: 'Polygon',
      opacity: 1,
      paint: { 'fill-color': '#000000', 'fill-opacity': 1, '_outline-color': '#ffffff' },
      layout: {},
      style_config: null,
    });
    const draft = {
      ...saved,
      opacity: 0.42,
      paint: { 'fill-color': '#123456', 'fill-opacity': 0.4, '_outline-color': '#abcdef' },
    };
    render(
      <LayerStyleEditor
        layer={draft}
        savedLayer={saved}
        onPaintChange={vi.fn()}
        onOpacityChange={onOpacityChange}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={onLayoutChange}
      />,
    );

    expect(screen.getByText('Pending style preview')).toBeInTheDocument();

    // Restores the exact saved paint (not FILL_DEFAULTS), saved layout, saved opacity.
    // fix(#461, codex P2): passes { replace: true } so the saved config is restored
    // verbatim — the builder-merge must not strand a discarded builder-only edit.
    // fix(#910, codex P2): and `restore: true`, which opts the commit boundary out of
    // the EDIT-05 normalization. A baseline that holds both fill keys (reachable via
    // Advanced JSON) would otherwise come back normalized, and since the dirty check
    // diffs against that same baseline the layer could never return to clean.
    await user.click(screen.getByRole('button', { name: 'Revert' }));
    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', null, saved.paint, { replace: true, restore: true });
    expect(onLayoutChange).toHaveBeenCalledWith('layer-1', saved.layout);
    expect(onOpacityChange).toHaveBeenCalledWith('layer-1', 1);
  });

  it('section-header Reset still clears to library defaults', async () => {
    const onStyleConfigChange = vi.fn();
    const onOpacityChange = vi.fn();
    const user = userEvent.setup();

    const saved = makeLayer({
      dataset_geometry_type: 'Polygon',
      opacity: 1,
      paint: { 'fill-color': '#000000', 'fill-opacity': 1 },
    });
    const draft = { ...saved, opacity: 0.42, paint: { 'fill-color': '#123456', 'fill-opacity': 0.4 } };
    render(
      <LayerStyleEditor
        layer={draft}
        savedLayer={saved}
        onPaintChange={vi.fn()}
        onOpacityChange={onOpacityChange}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    // Reset now confirms before destroying render mode + classification:
    // the header action opens the inline confirm, "Reset style" applies it.
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    expect(onStyleConfigChange).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Reset style' }));
    // fix(#910, codex P2): `replace` so Reset cannot leave the pattern colour stash
    // behind — the funnel's null-config branch would otherwise preserve the builder
    // block wholesale. With no other builder fields the config is still null.
    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', null, expect.objectContaining({
      'fill-color': expect.any(String),
      'fill-opacity': expect.any(Number),
    }), { replace: true });
    expect(onOpacityChange).toHaveBeenCalledWith('layer-1', 1);
  });

  it('section-header Reset can be cancelled without touching the style', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Polygon' })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Reset' }));
    await user.click(screen.getByRole('button', { name: 'Keep style' }));
    expect(onStyleConfigChange).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Reset style' })).toBeNull();
    // fix(#833): the confirm owned focus (autofocused Cancel) — dismissing it
    // hands focus back to the Reset trigger instead of dropping to <body>.
    expect(screen.getByRole('button', { name: 'Reset' })).toHaveFocus();
  });
});

describe('LayerStyleEditor - B-010 Advanced JSON strips builder-private keys', () => {
  it('hides _-prefixed + legacy builder keys from the Advanced Paint JSON textarea', async () => {
    const user = userEvent.setup();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: {
            'fill-color': '#123456',
            'fill-opacity': 0.4,
            '_outline-color': '#abcdef',
            'outline-color': '#000000',
            '_height_column': 'h',
          },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    // Expand Advanced JSON, then open the Paint block to reveal the textarea.
    await user.click(screen.getByRole('button', { name: /Advanced JSON/i }));
    await user.click(screen.getByRole('button', { name: 'Paint' }));

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    // Spec-valid key stays
    expect(textarea.value).toContain('fill-color');
    // Builder-private keys are stripped (would otherwise fail validateStyleMin on Apply)
    expect(textarea.value).not.toContain('_outline-color');
    expect(textarea.value).not.toContain('outline-color');
    expect(textarea.value).not.toContain('_height_column');
  });

  // fix(#770): Apply replaces the block wholesale while the textarea shows the
  // stripped copy — the onApply wrappers must re-merge the `_`-prefixed private
  // keys, or an edit-free open→Apply of the Layout block resets the layer's
  // zoom range (layout _minzoom/_maxzoom is the zoom sliders' only storage).
  it('re-merges layout _minzoom/_maxzoom on an unedited Layout Apply (#770)', async () => {
    const onLayoutChange = vi.fn();
    const user = userEvent.setup();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#123456' },
          layout: { '_minzoom': 5, '_maxzoom': 12 },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={onLayoutChange}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Advanced JSON/i }));
    await user.click(screen.getByRole('button', { name: 'Layout' }));
    await user.click(screen.getByRole('button', { name: 'Apply' }));

    expect(onLayoutChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      '_minzoom': 5,
      '_maxzoom': 12,
    }));
  });

  it('re-merges paint `_`-keys on Paint Apply while keeping the applied JSON (#770)', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#123456', 'fill-opacity': 0.4, '_outline-color': '#abcdef' },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Advanced JSON/i }));
    await user.click(screen.getByRole('button', { name: 'Paint' }));
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(textarea, {
      target: { value: JSON.stringify({ 'fill-color': '#ff0000', 'fill-opacity': 0.4 }) },
    });
    await user.click(screen.getByRole('button', { name: 'Apply' }));

    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'fill-color': '#ff0000',
      'fill-opacity': 0.4,
      '_outline-color': '#abcdef',
    });
  });
});

describe('hasUnsavedStyleChanges helper (SP-05)', () => {
  it('returns false when savedLayer is undefined', () => {
    const draft = makeLayer({ paint: { 'fill-color': '#abc' } });
    expect(hasUnsavedStyleChanges(draft, undefined)).toBe(false);
  });

  it('returns false when draft and saved are deep-equal in paint/layout/style_config', () => {
    const layer = makeLayer({ paint: { 'fill-color': '#abc' } });
    expect(hasUnsavedStyleChanges(layer, layer)).toBe(false);
    // Different object identity, same content
    expect(hasUnsavedStyleChanges({ ...layer, paint: { ...layer.paint } }, layer)).toBe(false);
  });

  it('returns true when draft.paint diverges from saved.paint', () => {
    const saved = makeLayer({ paint: { 'fill-color': '#aaa' } });
    const draft = { ...saved, paint: { 'fill-color': '#bbb' } };
    expect(hasUnsavedStyleChanges(draft, saved)).toBe(true);
  });

  it('returns true when draft.layout diverges from saved.layout', () => {
    const saved = makeLayer({ layout: {} });
    const draft = { ...saved, layout: { 'line-dasharray': [4, 2] } };
    expect(hasUnsavedStyleChanges(draft, saved)).toBe(true);
  });

  it('returns true when draft.style_config diverges from saved.style_config', () => {
    const saved = makeLayer({ style_config: null });
    const draft = { ...saved, style_config: { builder: { outlineWidth: 2 } } as MapLayerResponse['style_config'] };
    expect(hasUnsavedStyleChanges(draft, saved)).toBe(true);
  });
});

describe('LayerStyleEditor - dash presets', () => {

  it('warns about unsupported imported style state without mutating style config', () => {
    const onStyleConfigChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          style_config: {
            mode: 'third_party_breaks',
            column: 'traffic',
            ramp: 'custom',
          } as unknown as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.getByText(/This imported style uses settings the visual editor cannot safely change/i)).toBeInTheDocument();
    expect(onStyleConfigChange).not.toHaveBeenCalled();
  });

  it('renders 4 dash preset buttons for line layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Solid')).toBeInTheDocument();
    expect(screen.getByText('Dashed')).toBeInTheDocument();
    expect(screen.getByText('Dotted')).toBeInTheDocument();
    expect(screen.getByText('Dash-dot')).toBeInTheDocument();
  });

  it('does not render dash presets for polygon layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#ff0000' } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.queryByText('Solid')).not.toBeInTheDocument();
    expect(screen.queryByText('Dashed')).not.toBeInTheDocument();
  });

  it('calls onPaintChange with dash value when preset clicked', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByText('Dashed'));
    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'line-color': '#ff0000',
      'line-width': 2,
      'line-dasharray': [4, 2],
    });
  });

  it('removes paint and legacy layout dasharray when Solid clicked', async () => {
    const onPaintChange = vi.fn();
    const onLayoutChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          paint: { 'line-color': '#ff0000', 'line-width': 2, 'line-dasharray': [4, 2] },
          layout: { 'line-dasharray': [4, 2] },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={onLayoutChange}
      />,
    );

    await user.click(screen.getByText('Solid'));
    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'line-color': '#ff0000',
      'line-width': 2,
    });
    expect(onLayoutChange).toHaveBeenCalledWith('layer-1', {});
  });

  it('highlights the active preset based on current layout', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ layout: { 'line-dasharray': [1, 2] } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    const dottedBtn = screen.getByText('Dotted');
    expect(dottedBtn.className).toContain('bg-primary');

    const solidBtn = screen.getByText('Solid');
    expect(solidBtn.className).not.toContain('bg-primary');
  });
});

describe('LayerStyleEditor - line paint controls', () => {
  it('renders gap width, blur, and offset controls with existing line controls', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Color')).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Line opacity' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Width' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Gap' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Blur' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Offset' })).toBeInTheDocument();
    expect(screen.getByText('Solid')).toBeInTheDocument();
  });

  it('writes explicit line gap width, blur, and offset paint values', () => {
    const onPaintChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    fireEvent.keyDown(screen.getByRole('slider', { name: 'Gap' }), { key: 'ArrowRight' });
    fireEvent.keyDown(screen.getByRole('slider', { name: 'Blur' }), { key: 'ArrowRight' });
    fireEvent.keyDown(screen.getByRole('slider', { name: 'Offset' }), { key: 'ArrowLeft' });

    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'line-color': '#ff0000',
      'line-width': 2,
      'line-gap-width': 0.25,
    });
    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'line-color': '#ff0000',
      'line-width': 2,
      'line-blur': 0.25,
    });
    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'line-color': '#ff0000',
      'line-width': 2,
      'line-offset': -0.25,
    });
  });

  it('emits line width zoom expressions from the first-class editor', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(within(screen.getByRole('group', { name: 'Width mode' })).getByRole('button', { name: 'Varies by zoom' }));

    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'line-color': '#ff0000',
      'line-width': ['interpolate', ['linear'], ['zoom'], 4, 2, 12, 2],
    });
  });

  it('preserves data-driven width messaging instead of exposing zoom width editing', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({
          paint: { 'line-color': '#ff0000', 'line-width': ['step', ['get', 'traffic'], 1, 10, 4] },
          style_config: { column: 'traffic', target: 'width', mode: 'graduated' } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Width by: traffic')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Width mode' })).not.toBeInTheDocument();
  });

  it('shows unsupported line zoom-plus-data expressions without flattening them', () => {
    const onPaintChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          paint: {
            'line-color': '#ff0000',
            'line-width': ['interpolate', ['linear'], ['zoom'], 4, ['get', 'width'], 12, 6],
          },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.getByText('This property uses an unsupported expression. Use Advanced JSON to edit it.')).toBeInTheDocument();
    expect(onPaintChange).not.toHaveBeenCalled();
  });

  it('exposes first-class line gradient authoring controls (Phase 256)', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    // Phase 256 introduces first-class gradient authoring on line layers
    // (replaces the Phase 247 deferral where gradients were JSON-only).
    expect(screen.getByRole('button', { name: 'Gradient' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Solid color' })).toBeInTheDocument();
  });

  it('accepts line-gradient through advanced paint JSON', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();
    const gradientPaint = {
      'line-color': '#ff0000',
      'line-width': 2,
      'line-gradient': ['interpolate', ['linear'], ['line-progress'], 0, '#00f', 1, '#0f0'],
    };

    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Advanced JSON' }));
    await user.click(screen.getByRole('button', { name: 'Paint' }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: JSON.stringify(gradientPaint) } });
    await user.click(screen.getByRole('button', { name: 'Apply' }));

    expect(onPaintChange).toHaveBeenCalledWith('layer-1', gradientPaint);
  });
});

describe('LayerStyleEditor - circle zoom expression controls', () => {
  it('emits circle radius zoom expressions from the point style editor', async () => {
    const onPaintChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'circle-color': '#ff0000', 'circle-radius': 5 },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(within(screen.getByRole('group', { name: 'Radius mode' })).getByRole('button', { name: 'Varies by zoom' }));

    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'circle-color': '#ff0000',
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 5, 12, 5],
    });
  });

  it('edits supported circle opacity expressions without raw JSON', () => {
    const onPaintChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: {
            'circle-color': '#ff0000',
            'circle-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.4, 12, 1],
            'circle-radius': 5,
          },
        })}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Point opacity Stop 2 value'), { target: { value: '0.75' } });

    expect(onPaintChange).toHaveBeenCalledWith('layer-1', {
      'circle-color': '#ff0000',
      'circle-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.4, 12, 0.75],
      'circle-radius': 5,
    });
  });
});

describe('LayerStyleEditor - fill/stroke toggles', () => {
  it('renders fill and stroke toggles for polygon layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.3 } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('Toggle fill visibility')).toBeInTheDocument();
    expect(screen.getByLabelText('Toggle stroke visibility')).toBeInTheDocument();
  });

  it('renders stroke toggle only for circle layers (no fill toggle)', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Point', paint: { 'circle-color': '#ff0000' } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText('Toggle fill visibility')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Toggle stroke visibility')).toBeInTheDocument();
  });

  it('renders no toggles for line layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText('Toggle fill visibility')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Toggle stroke visibility')).not.toBeInTheDocument();
  });

  it('toggle fill OFF sets fill-opacity to 0 and saves current value in style_config', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.5 },
          style_config: { builder: { outlineColor: '#000', outlineWidth: 1 } } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle fill visibility'));
    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      builder: expect.objectContaining({
        fillDisabled: true,
        fillOpacitySaved: 0.5,
      }),
    }), expect.objectContaining({
      'fill-opacity': 0,
    }));
  });

  it('toggle fill ON restores saved opacity and removes builder flags', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0 },
          style_config: { builder: { fillDisabled: true, fillOpacitySaved: 0.5, outlineColor: '#000', outlineWidth: 1 } } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle fill visibility'));
    const [, config, paint] = onStyleConfigChange.mock.calls[0];
    expect(paint['fill-opacity']).toBe(0.5);
    expect(config.builder.fillDisabled).toBeUndefined();
    expect(config.builder.fillOpacitySaved).toBeUndefined();
  });

  it('toggle stroke OFF on polygon sets builder outline width to 0', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.3 },
          style_config: { builder: { outlineColor: '#000', outlineWidth: 2 } } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle stroke visibility'));
    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      builder: expect.objectContaining({
        strokeDisabled: true,
        outlineWidthSaved: 2,
        outlineWidth: 0,
      }),
    }), expect.not.objectContaining({ '_stroke-disabled': true }));
  });

  it('toggle stroke OFF on circle sets circle-stroke-width to 0', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'circle-color': '#ff0000', 'circle-stroke-color': '#000', 'circle-stroke-width': 3 },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle stroke visibility'));
    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      builder: expect.objectContaining({
        strokeDisabled: true,
        outlineWidthSaved: 3,
      }),
    }), expect.objectContaining({
      'circle-stroke-width': 0,
    }));
  });

  it('toggle stroke ON on circle restores saved width', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'circle-color': '#ff0000', 'circle-stroke-color': '#000', 'circle-stroke-width': 0 },
          style_config: { builder: { strokeDisabled: true, outlineWidthSaved: 3 } } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText('Toggle stroke visibility'));
    const [, config, paint] = onStyleConfigChange.mock.calls[0];
    expect(paint['circle-stroke-width']).toBe(3);
    expect(config).toBeNull();
  });

  it('collapses fill controls when fill is disabled', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0 },
          style_config: { builder: { fillDisabled: true, outlineColor: '#000', outlineWidth: 1 } } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    // Fill toggle should be present but fill controls (opacity slider) should be hidden
    expect(screen.getByLabelText('Toggle fill visibility')).toBeInTheDocument();
    // The fill opacity slider label should not be visible when collapsed
    // We check that the fill section's color/opacity controls are not present
    // The "Stroke" section should still be visible
    expect(screen.getByText('Stroke')).toBeInTheDocument();
  });

  it('collapses stroke controls when stroke is disabled on polygon', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.3 },
          style_config: { builder: { outlineColor: '#000', outlineWidth: 0, strokeDisabled: true } } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    // Stroke toggle present but stroke controls collapsed
    expect(screen.getByLabelText('Toggle stroke visibility')).toBeInTheDocument();
    expect(screen.getByText('Fill')).toBeInTheDocument();
  });
});

describe('LayerStyleEditor - render mode (heatmap)', () => {
  it('does NOT render a "Render as" section inside LayerStyleEditor for point layers (POLISH-01)', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Point', paint: { 'circle-color': '#ff0000' } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    // POLISH-01: the redundant dropdown was removed; LayerStyleEditor no longer
    // renders a "Render as" section heading for point layers.
    expect(screen.queryByText('Render as')).not.toBeInTheDocument();
  });

  it('does NOT render "Render as" dropdown for polygon layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#ff0000' } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.queryByText('Render as')).not.toBeInTheDocument();
  });

  it('does NOT render "Render as" dropdown for line layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'LineString', paint: { 'line-color': '#ff0000' } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.queryByText('Render as')).not.toBeInTheDocument();
  });

  it('shows heatmap controls when render_mode is heatmap', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'heatmap-radius': 30, 'heatmap-intensity': 1 },
          style_config: { mode: 'categorical', column: '', ramp: '', render_mode: 'heatmap' } as unknown as import('@/types/api').StyleConfig,
          dataset_column_info: [{ name: 'count', type: 'integer' }],
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    // Heatmap controls should be present
    expect(screen.getByText('Weight column')).toBeInTheDocument();
    expect(screen.getByText('Color ramp')).toBeInTheDocument();
    expect(screen.getByText('Radius')).toBeInTheDocument();
    expect(screen.getByText('Intensity')).toBeInTheDocument();

    // Circle controls should be absent
    expect(screen.queryByLabelText('Toggle stroke visibility')).not.toBeInTheDocument();
  });

  it('shows symbol controls when render_mode is symbol', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: {},
          style_config: {
            render_mode: 'symbol',
            symbol: { iconImage: 'marker', iconSize: 1 },
          } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    // Symbol rendering is separate from label_config-backed feature labels.
    // POLISH-01: the render-as dropdown is removed; "Symbol appearance" section heading is
    // the canonical signal that the symbol editor is rendered.
    expect(screen.getByText('Symbol appearance')).toBeInTheDocument();
    expect(screen.getByLabelText('Icon')).toHaveValue('marker');
    expect(screen.getByRole('slider', { name: 'Size' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Rotation' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Toggle stroke visibility')).not.toBeInTheDocument();
  });

  it('shows cluster authoring controls and writes builder config only', () => {
    const onStyleConfigChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          dataset_feature_count: 100,
          paint: { 'circle-color': '#ff0000', 'circle-radius': 5 },
          style_config: {
            render_mode: 'cluster',
            builder: {
              clusterRadius: 36,
              clusterMaxZoom: 12,
              clusterColor: '#3b82f6',
              clusterTextColor: '#ffffff',
              clusterTextSize: 13,
            },
          } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    expect(screen.getByText('Cluster appearance')).toBeInTheDocument();
    expect(screen.getByText('Tune cluster radius, expansion zoom, and count labels.')).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Cluster radius' })).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Max cluster zoom' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cluster color' })).toHaveAttribute('title', '#3b82f6');
    expect(screen.getByRole('button', { name: 'Count color' })).toHaveAttribute('title', '#ffffff');
    expect(screen.getByRole('slider', { name: 'Count size' })).toBeInTheDocument();

    fireEvent.keyDown(screen.getByRole('slider', { name: 'Cluster radius' }), { key: 'ArrowRight' });

    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      render_mode: 'cluster',
      builder: expect.objectContaining({
        clusterRadius: 37,
        clusterMaxZoom: 12,
        clusterTextSize: 13,
      }),
    }), { 'circle-color': '#ff0000', 'circle-radius': 5 });
  });

  // ux(#839): counts are opt-out via clusterShowCounts, independent of Labels.
  it('toggles cluster count labels off and hides the count controls', () => {
    const onStyleConfigChange = vi.fn();
    const clusterLayer = (builder: Record<string, unknown>) => makeLayer({
      dataset_geometry_type: 'Point',
      dataset_feature_count: 100,
      paint: { 'circle-color': '#ff0000', 'circle-radius': 5 },
      style_config: { render_mode: 'cluster', builder } as import('@/types/api').StyleConfig,
    });

    const { unmount } = render(
      <LayerStyleEditor
        layer={clusterLayer({})}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    const toggle = screen.getByRole('switch', { name: 'Show counts' });
    expect(toggle).toBeChecked(); // absent flag = counts on
    fireEvent.click(toggle);
    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      builder: expect.objectContaining({ clusterShowCounts: false }),
    }), { 'circle-color': '#ff0000', 'circle-radius': 5 });
    unmount();

    render(
      <LayerStyleEditor
        layer={clusterLayer({ clusterShowCounts: false })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );
    expect(screen.getByRole('switch', { name: 'Show counts' })).not.toBeChecked();
    expect(screen.queryByRole('button', { name: 'Count color' })).not.toBeInTheDocument();
    expect(screen.queryByRole('slider', { name: 'Count size' })).not.toBeInTheDocument();
  });

  it('writes symbol icon settings into style_config and keeps paint clean', () => {
    const onStyleConfigChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'circle-color': '#ff0000' },
          style_config: {
            render_mode: 'symbol',
            symbol: { iconImage: 'marker' },
          } as import('@/types/api').StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Icon'), { target: { value: 'bus' } });

    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      render_mode: 'symbol',
      symbol: expect.objectContaining({ iconImage: 'bus' }),
    }), { 'circle-color': '#ff0000' });
  });

  it('stores heatmap weight metadata in style_config and keeps paint clean', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Point',
          paint: { 'heatmap-radius': 30, 'heatmap-intensity': 1 },
          style_config: { render_mode: 'heatmap', builder: { heatmapRamp: 'YlOrRd' } } as import('@/types/api').StyleConfig,
          dataset_column_info: [{ name: 'count', type: 'integer' }],
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    // POLISH-01: render-as dropdown removed; weight column is now the first (and only) combobox
    const [weightSelect] = screen.getAllByRole('combobox');
    await user.click(weightSelect);
    await user.click(screen.getByRole('option', { name: 'count' }));

    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', expect.objectContaining({
      builder: expect.objectContaining({
        heatmapRamp: 'YlOrRd',
        heatmapWeightColumn: 'count',
      }),
    }), expect.objectContaining({
      'heatmap-weight': ['get', 'count'],
    }));
    const paint = onStyleConfigChange.mock.calls[0][2];
    expect(paint['_heatmap-weight-column']).toBeUndefined();
    expect(paint['_heatmap-ramp']).toBeUndefined();
  });
});

describe('LayerStyleEditor — line-gradient integration', () => {
  it('integration: line-gradient renders Solid/Gradient toggle inside line controls', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Solid color' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Gradient' })).toBeInTheDocument();
  });

  it('integration: line-gradient toggle does not render for polygon layers', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Polygon', paint: { 'fill-color': '#abcdef' } })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Gradient' })).not.toBeInTheDocument();
  });

  it('integration: clicking Gradient line-gradient mode commits builder.lineGradient.stops and a canonical paint expression', async () => {
    const onPaintChange = vi.fn();
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();
    render(
      <LayerStyleEditor
        layer={makeLayer()}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Gradient' }));
    // paint MUST contain a canonical line-gradient array
    const paintCalls = onPaintChange.mock.calls as Array<[string, Record<string, unknown>]>;
    const paintWithGradient = paintCalls.find((c) => Array.isArray(c[1]['line-gradient']));
    expect(paintWithGradient).toBeDefined();
    // styleConfig MUST contain builder.lineGradient.stops
    const styleConfigCalls = onStyleConfigChange.mock.calls as Array<[string, { builder?: { lineGradient?: { stops?: unknown[] } } } | null, Record<string, unknown>]>;
    const builderUpdate = styleConfigCalls.find((c) => Array.isArray(c[1]?.builder?.lineGradient?.stops));
    expect(builderUpdate).toBeDefined();
  });
});

describe('LayerEditorPanel — layer switch state isolation (WR-01)', () => {
  const handlers = {
    onTabChange: vi.fn(),
    onPaintChange: vi.fn(),
    onOpacityChange: vi.fn(),
    onFilterChange: vi.fn(),
    onLabelChange: vi.fn(),
    onPopupChange: vi.fn(),
    onStyleConfigChange: vi.fn(),
    onLayoutChange: vi.fn(),
    onRenderModeChange: vi.fn(),
    onRemove: vi.fn(),
  };

  it('switching from layer with no gradient to layer with gradient resets local mode to Gradient (no stale solid)', () => {
    const layerA: MapLayerResponse = {
      ...makeLayer({ id: 'layer-A', paint: { 'line-color': '#ff0000' } }),
    };
    const gradientExpr = stopsToLineGradientExpression([
      { position: 0, color: '#000' },
      { position: 1, color: '#fff' },
    ]);
    const layerB: MapLayerResponse = {
      ...makeLayer({
        id: 'layer-B',
        paint: { 'line-gradient': gradientExpr },
        style_config: { builder: { lineGradient: { stops: [{ position: 0, color: '#000' }, { position: 1, color: '#fff' }] } } } as import('@/types/api').StyleConfig,
      }),
    };

    const { rerender } = render(
      <LayerEditorPanel layer={layerA} activeTab="style" handlers={handlers} onClose={vi.fn()} />,
    );
    // Layer A starts in Solid mode (no gradient)
    expect(screen.getByRole('button', { name: 'Solid color' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Gradient' })).toHaveAttribute('aria-pressed', 'false');

    // Switch to layer B (which has a canonical gradient). With key={layer.id},
    // the LayerStyleEditor remounts and LineGradientControls re-derives initialMode
    // from layer B's paint, putting the toggle into Gradient mode.
    rerender(<LayerEditorPanel layer={layerB} activeTab="style" handlers={handlers} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Gradient' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Solid color' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('switching from layer with gradient to layer without gradient resets local mode to Solid', () => {
    const gradientExpr = stopsToLineGradientExpression([
      { position: 0, color: '#000' },
      { position: 1, color: '#fff' },
    ]);
    const layerA: MapLayerResponse = {
      ...makeLayer({
        id: 'layer-A',
        paint: { 'line-gradient': gradientExpr },
        style_config: { builder: { lineGradient: { stops: [{ position: 0, color: '#000' }, { position: 1, color: '#fff' }] } } } as import('@/types/api').StyleConfig,
      }),
    };
    const layerB: MapLayerResponse = {
      ...makeLayer({ id: 'layer-B', paint: { 'line-color': '#ff0000' } }),
    };

    const { rerender } = render(
      <LayerEditorPanel layer={layerA} activeTab="style" handlers={handlers} onClose={vi.fn()} />,
    );
    expect(screen.getByRole('button', { name: 'Gradient' })).toHaveAttribute('aria-pressed', 'true');

    rerender(<LayerEditorPanel layer={layerB} activeTab="style" handlers={handlers} onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Solid color' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Gradient' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('renders inspector tabs and back control with visible keyboard focus treatment', () => {
    render(
      <LayerEditorPanel
        layer={makeLayer()}
        activeTab="filter"
        handlers={handlers}
        onClose={vi.fn()}
        isDrillDown={true}
      />,
    );

    const tablist = screen.getByRole('tablist');
    const filterTab = within(tablist).getByRole('tab', { name: 'Filter' });
    expect(filterTab).toHaveAttribute('aria-selected', 'true');
    expect(filterTab.className).toContain('focus-visible:ring-2');
    expect(screen.getByRole('button', { name: 'Back to layers' }).className).toContain('focus-visible:ring-2');
  });
});

// ---------------------------------------------------------------------------
// PB-02 / PERF-04: Master opacity slider debounce (100ms)
// ---------------------------------------------------------------------------
describe('LayerStyleEditor - opacity slider debounce (PB-02)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('rapid opacity changes coalesce into ONE onOpacityChange call after 100ms', () => {
    const onOpacityChange = vi.fn();

    const { rerender } = render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          opacity: 1,
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 1, '_outline-color': '#000000' },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={onOpacityChange}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    // Find the master opacity slider (aria-label = "Layer opacity")
    const slider = screen.getByRole('slider', { name: 'Layer opacity' });

    // Simulate 3 rapid keydown events on the slider to change the value
    // Radix Slider responds to ArrowLeft/ArrowRight key events
    act(() => {
      fireEvent.keyDown(slider, { key: 'ArrowLeft' });
      fireEvent.keyDown(slider, { key: 'ArrowLeft' });
      fireEvent.keyDown(slider, { key: 'ArrowLeft' });
    });

    // Before debounce window: onOpacityChange should NOT have been called yet
    expect(onOpacityChange).not.toHaveBeenCalled();

    // Advance time past 100ms debounce window
    act(() => {
      vi.advanceTimersByTime(100);
    });

    // After debounce: exactly 1 call (last value wins)
    expect(onOpacityChange).toHaveBeenCalledTimes(1);
    expect(onOpacityChange).toHaveBeenCalledWith('layer-1', expect.any(Number));

    rerender(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          opacity: 1,
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 1, '_outline-color': '#000000' },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={onOpacityChange}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );
  });

  it('does not call onOpacityChange immediately on mount (no spurious call on first render)', () => {
    const onOpacityChange = vi.fn();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'LineString',
          opacity: 0.5,
          paint: { 'line-color': '#ff0000', 'line-width': 2 },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={onOpacityChange}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );

    // Advance past the debounce window — no interaction happened
    act(() => {
      vi.advanceTimersByTime(200);
    });

    // No call because opacity hasn't changed from the prop value
    expect(onOpacityChange).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// EDIT-02: Always-visible vector Reset button in appearance section header
// ---------------------------------------------------------------------------
describe('LayerStyleEditor — EDIT-02 always-visible Reset in appearance section', () => {
  it('Reset button is present in the appearance section even when the layer is NOT dirty (no savedLayer)', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 1 },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );
    // The always-visible Reset button must be present regardless of dirty state.
    // When no savedLayer is provided the dirty banner is absent, but the button must
    // still render in the appearance section header.
    expect(screen.queryByText('Pending style preview')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reset' })).toBeInTheDocument();
  });

  it('Reset button calls handleResetStyle and resets polygon paint to FILL_DEFAULTS', async () => {
    const onStyleConfigChange = vi.fn();
    const onOpacityChange = vi.fn();
    const user = userEvent.setup();

    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#abcdef', 'fill-opacity': 0.3 },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={onOpacityChange}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    // Reset now confirms first — apply via the inline confirm's "Reset style".
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    await user.click(screen.getByRole('button', { name: 'Reset style' }));
    // fix(#910, codex P2): `replace` so Reset cannot leave the pattern colour stash
    // behind — the funnel's null-config branch would otherwise preserve the builder
    // block wholesale. With no other builder fields the config is still null.
    expect(onStyleConfigChange).toHaveBeenCalledWith('layer-1', null, expect.objectContaining({
      'fill-color': expect.any(String),
      'fill-opacity': expect.any(Number),
    }), { replace: true });
    expect(onOpacityChange).toHaveBeenCalledWith('layer-1', 1);
  });
});

// ---------------------------------------------------------------------------
// EDIT-05: fill-color / fill-pattern mutual exclusion via handleFillPatternChange
// ---------------------------------------------------------------------------
describe('LayerStyleEditor — EDIT-05 fill-color / fill-pattern mutual exclusion', () => {
  // fix(#910): the handler now stashes the solid color in style_config.builder,
  // so it emits through onStyleConfigChange (config, paint) rather than
  // onPaintChange. The both-keys-never invariant is asserted on that paint.
  function lastStyleConfigCall(fn: ReturnType<typeof vi.fn>) {
    const calls = fn.mock.calls as Array<
      [string, StyleConfig | null, Record<string, unknown>, { replace?: boolean } | undefined]
    >;
    expect(calls.length).toBeGreaterThan(0);
    const [, config, paint, opts] = calls[calls.length - 1];
    expect(Object.values(paint).filter((v) => v === undefined)).toHaveLength(0);
    return { config, paint, opts };
  }

  it('switching to a pattern emits paint that has fill-pattern but NOT fill-color, and stashes the color', () => {
    const onStyleConfigChange = vi.fn();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': '#ff0000', 'fill-opacity': 0.8 },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    // Click the Hatch pattern swatch (rendered by FillPatternPicker inside FillEditor)
    fireEvent.click(screen.getByRole('button', { name: 'Hatch' }));

    const { config, paint } = lastStyleConfigCall(onStyleConfigChange);
    // Pattern key is set
    expect(paint['fill-pattern']).toBe('geolens-fill-hatch');
    // Color key is DELETED — not undefined, completely absent
    expect('fill-color' in paint).toBe(false);
    // ...but stashed so the round-trip can restore it
    expect(config?.builder?.fillColorSaved).toBe('#ff0000');
  });

  it('clearing a pattern (None) emits paint that has fill-color but NOT fill-pattern', () => {
    const onStyleConfigChange = vi.fn();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-pattern': 'geolens-fill-hatch', 'fill-opacity': 0.8 },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    // Click the None swatch (first button with label "None" in the FillPatternPicker)
    const noneButtons = screen.getAllByRole('button', { name: 'None' });
    fireEvent.click(noneButtons[0]);

    const { paint } = lastStyleConfigCall(onStyleConfigChange);
    // fill-pattern key is DELETED — completely absent, not set to undefined
    expect('fill-pattern' in paint).toBe(false);
    // fill-color is restored
    expect(typeof paint['fill-color']).toBe('string');
  });

  // fix(#910): the acceptance case that fails if either alias table is missed —
  // the stash arrives from style_config (i.e. the save-and-reload path), not
  // from this session's paint.
  it('restores a stashed fillColorSaved on None and clears the stash', () => {
    const onStyleConfigChange = vi.fn();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-pattern': 'geolens-fill-hatch', 'fill-opacity': 0.8 },
          style_config: { builder: { fillColorSaved: '#ff0000' } },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getAllByRole('button', { name: 'None' })[0]);

    const { config, paint, opts } = lastStyleConfigCall(onStyleConfigChange);
    expect(paint['fill-color']).toBe('#ff0000');
    expect('fill-pattern' in paint).toBe(false);
    expect(config?.builder?.fillColorSaved).toBeUndefined();
    // fix(#910, codex P2): with fillColorSaved the only builder field, the emitted
    // config collapses to null — and a null config means "keep the existing builder"
    // in handleStyleConfigChange, which would resurrect the stash. `replace` is what
    // makes the clear stick; the funnel side is pinned in use-layer-map-sync.test.ts.
    expect(config).toBeNull();
    expect(opts?.replace).toBe(true);
  });

  // fix(#910, codex P2): pattern-to-pattern finds no fill-color to stash, so the
  // handler must carry the existing stash forward instead of dropping it.
  // fix(#910, codex P2): Reset must drop the stash. A layer with other builder
  // fields keeps them, so the config is not null and `replace` is what makes the
  // removal stick through the funnel.
  it('drops the stash on Reset while keeping the rest of the builder', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-pattern': 'geolens-fill-hatch' },
          style_config: { builder: { fillColorSaved: '#ff0000', outlineWidth: 3 } },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Reset' }));
    await user.click(screen.getByRole('button', { name: 'Reset style' }));

    const { config, opts } = lastStyleConfigCall(onStyleConfigChange);
    expect(config?.builder?.fillColorSaved).toBeUndefined();
    expect(config?.builder?.outlineWidth).toBe(3);
    expect(opts?.replace).toBe(true);
  });

  // fix(#910, codex P1): Reset destroys the classification and the render mode. An
  // earlier attempt at the stash clear rebuilt the config from the WHOLE style_config,
  // which `replace` then persisted verbatim — mode, column and render_mode survived a
  // Reset. The reset config is builder-only for exactly that reason.
  it('drops mode, column and render_mode on Reset', async () => {
    const onStyleConfigChange = vi.fn();
    const user = userEvent.setup();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': ['match', ['get', 'era'], 'a', '#f00', '#0f0'] },
          style_config: {
            mode: 'categorical',
            column: 'era',
            ramp: 'Set2',
            categories: [{ value: 'a', color: '#f00' }],
            builder: { outlineWidth: 3, fillColorSaved: '#ff0000' },
          },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Reset' }));
    await user.click(screen.getByRole('button', { name: 'Reset style' }));

    const { config, opts } = lastStyleConfigCall(onStyleConfigChange);
    expect(opts?.replace).toBe(true);
    expect(config?.mode).toBeUndefined();
    expect(config?.column).toBeUndefined();
    expect(config?.categories).toBeUndefined();
    expect((config as { render_mode?: string } | null)?.render_mode).toBeUndefined();
    // The builder block survives, minus the pattern colour stash.
    expect(config?.builder?.outlineWidth).toBe(3);
    expect(config?.builder?.fillColorSaved).toBeUndefined();
  });

  // fix(#910, codex P2): the delete is what destroyed classifications. It must never
  // touch an expression — only a solid colour is stashable, and only a solid colour
  // is safe to remove. Reachable without a classification: Advanced JSON can write an
  // expression into fill-color with no style_config mode, and the picker is live there.
  it('never deletes an expression-valued fill-color when a pattern is applied', () => {
    const ramp = ['match', ['get', 'era'], 'pre-war', '#ff0000', '#00ff00'];
    const onStyleConfigChange = vi.fn();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-color': ramp, 'fill-opacity': 0.3 },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Dots' }));

    const { config, paint } = lastStyleConfigCall(onStyleConfigChange);
    expect(paint['fill-color']).toEqual(ramp);
    expect(paint['fill-pattern']).toBe('geolens-fill-dots');
    // Nothing stashable, so nothing stashed.
    expect(config?.builder?.fillColorSaved).toBeUndefined();
  });

  // fix(#910, codex P2): the stash is declared `string` but arrives from an open
  // `style_config`, so an API-authored layer can hold junk. Restoring that on None
  // would paint a colour MapLibre rejects.
  it('falls back to the default colour when the stash is not a usable colour', () => {
    const onStyleConfigChange = vi.fn();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-pattern': 'geolens-fill-hatch' },
          style_config: { builder: { fillColorSaved: 42 } } as unknown as StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getAllByRole('button', { name: 'None' })[0]);

    const { paint } = lastStyleConfigCall(onStyleConfigChange);
    expect('fill-pattern' in paint).toBe(false);
    expect(typeof paint['fill-color']).toBe('string');
  });

  // fix(#910, codex P2): None means a plain solid fill, so an orphaned colour
  // classification must not survive it. Reachable when Advanced JSON or the AI
  // replace_paint action swaps a categorical fill-color expression for a pattern-only
  // paint object: the config outlives its expression, and None then left the layer
  // drawing solid while the editor and legend still claimed attribute styling.
  it('clears an orphaned colour classification when None restores a solid fill', () => {
    const onStyleConfigChange = vi.fn();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          // The replace_paint aftermath: pattern only, no fill-color expression left.
          paint: { 'fill-pattern': 'geolens-fill-hatch' },
          style_config: {
            mode: 'categorical',
            column: 'zone',
            ramp: 'Set2',
            categories: [{ value: 'a', color: '#e41a1c' }],
          } as StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getAllByRole('button', { name: 'None' })[0]);

    const { config, paint } = lastStyleConfigCall(onStyleConfigChange);
    expect('fill-pattern' in paint).toBe(false);
    expect(typeof paint['fill-color']).toBe('string');
    // The classification is gone, so the legend and the editor agree with the map.
    expect(config?.mode).toBeUndefined();
    expect(config?.column).toBeUndefined();
    expect(config?.categories).toBeUndefined();
  });

  // The mirror: a classification the fill picker has no business touching survives.
  it('leaves a non-colour classification alone when None restores a solid fill', () => {
    const onStyleConfigChange = vi.fn();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-pattern': 'geolens-fill-hatch' },
          style_config: {
            mode: 'graduated',
            column: 'height',
            ramp: 'Blues',
            target: 'width',
          } as StyleConfig,
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getAllByRole('button', { name: 'None' })[0]);

    const { config } = lastStyleConfigCall(onStyleConfigChange);
    expect(config?.mode).toBe('graduated');
    expect(config?.target).toBe('width');
  });

  it('keeps the stash when switching from one pattern straight to another', () => {
    const onStyleConfigChange = vi.fn();
    render(
      <LayerStyleEditor
        layer={makeLayer({
          dataset_geometry_type: 'Polygon',
          paint: { 'fill-pattern': 'geolens-fill-hatch', 'fill-opacity': 0.8 },
          style_config: { builder: { fillColorSaved: '#ff0000' } },
        })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Dots' }));

    const { config, paint } = lastStyleConfigCall(onStyleConfigChange);
    expect(paint['fill-pattern']).toBe('geolens-fill-dots');
    expect(config?.builder?.fillColorSaved).toBe('#ff0000');
  });
});

describe('LayerStyleEditor — POLISH-01 single render-as control', () => {
  it('point layer (geomType=circle) renders NO render-as section heading inside LayerStyleEditor', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'Point' })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );
    // The redundant StyleControlSection heading with "Render as" title is gone.
    // NOTE: DataDrivenStyleEditor renders its own comboboxes (e.g. "Categorical")
    // which are unrelated to render-as — we only assert the section heading is absent.
    expect(screen.queryAllByText(/render as/i)).toHaveLength(0);
  });

  it('LineString layer also renders no render-as section (no regression)', () => {
    render(
      <LayerStyleEditor
        layer={makeLayer({ dataset_geometry_type: 'LineString' })}
        onPaintChange={vi.fn()}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={vi.fn()}
        onLayoutChange={vi.fn()}
      />,
    );
    expect(screen.queryAllByText(/render as/i)).toHaveLength(0);
  });
});

// fix(#916 review): symbol mode keeps circle paint on the layer and the switch
// back to Point restores style_config.savedCirclePaint — so an Advanced JSON
// paint edit must update that saved copy too, or it is silently discarded.
describe('LayerStyleEditor - symbol-mode advanced paint edits', () => {
  const symbolLayer = () => ({
    ...makeLayer({ dataset_geometry_type: 'Point' }),
    paint: { 'circle-color': '#ff0000', 'circle-radius': 5 },
    style_config: {
      render_mode: 'symbol',
      savedCirclePaint: { 'circle-color': '#ff0000', 'circle-radius': 5 },
      symbol: { iconImage: 'marker' },
    },
  }) as unknown as MapLayerResponse;

  it('writes the applied paint to savedCirclePaint as well as paint', () => {
    const onStyleConfigChange = vi.fn();
    const onPaintChange = vi.fn();
    render(
      <LayerStyleEditor
        layer={symbolLayer()}
        onPaintChange={onPaintChange}
        onOpacityChange={vi.fn()}
        onStyleConfigChange={onStyleConfigChange}
        onLayoutChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /advanced json/i }));
    fireEvent.click(screen.getByRole('button', { name: /paint/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /paint/i }), {
      target: { value: JSON.stringify({ 'circle-color': '#00ff00', 'circle-radius': 9 }) },
    });
    fireEvent.click(screen.getByRole('button', { name: /apply/i }));

    expect(onPaintChange).not.toHaveBeenCalled();
    const [, config, paint] = onStyleConfigChange.mock.calls.at(-1)!;
    expect(paint).toEqual({ 'circle-color': '#00ff00', 'circle-radius': 9 });
    expect(config.savedCirclePaint).toEqual({ 'circle-color': '#00ff00', 'circle-radius': 9 });
  });
});
