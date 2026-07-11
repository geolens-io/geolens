import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { ColorizedGeometryIcon, LayerTypeIcon, type LayerTypeIconLayer } from '../layer-icons';

// Guards the contract LegendPlugin + StackRow both depend on: callers pass the
// capability KIND ('raster'/'vrt'), not the raw layer_type ('raster_geolens').
// Passing the wrong value fell through to a polygon swatch — the "purple
// polygon for raster layers in the legend" bug.
describe('ColorizedGeometryIcon raster/vrt contract', () => {
  it('renders the grid (raster) icon for kind "raster", not a polygon', () => {
    const { container } = render(
      <ColorizedGeometryIcon geometryType={null} colors={[]} layerId="x" layerType="raster" />,
    );
    expect(container.querySelector('.lucide-grid-3x3')).not.toBeNull();
  });

  it('renders the layers (vrt) icon for kind "vrt"', () => {
    const { container } = render(
      <ColorizedGeometryIcon geometryType={null} colors={[]} layerId="x" layerType="vrt" />,
    );
    expect(container.querySelector('.lucide-layers')).not.toBeNull();
  });
});

// fix(#452): replacement for the deleted StackRow.guard04.test.tsx. The
// extractStyleHints memo moved verbatim into LayerTypeIcon, where a vi.spyOn
// seam can no longer observe the (now intra-module) call. Instead, count
// property READS on the paint object — extractStyleHints touches
// `_stroke-disabled` on every compute and nothing else in the render path
// does, so the read count is a spy-free recomputation counter. Guards the
// `eslint-disable react-hooks/exhaustive-deps` memo: keying it on the local
// `paint`/`layout` fallbacks (fresh objects per render) would silently kill
// memoization for every stack row.
describe('LayerTypeIcon style-hint memoization (GUARD-04)', () => {
  function countingPaint() {
    let reads = 0;
    const paint: Record<string, unknown> = {};
    Object.defineProperty(paint, '_stroke-disabled', {
      get() {
        reads += 1;
        return false;
      },
      enumerable: true,
    });
    return { paint, reads: () => reads };
  }

  const baseLayer = (paint: Record<string, unknown>): LayerTypeIconLayer => ({
    dataset_geometry_type: 'POLYGON',
    layer_type: 'vector_geolens',
    paint,
    layout: {},
    opacity: 1,
    style_config: null,
  });

  it('does not recompute hints on unrelated prop changes, but does on a paint change', () => {
    const { paint, reads } = countingPaint();
    const layer = baseLayer(paint);
    const { rerender } = render(<LayerTypeIcon layer={layer} iconId="icon-a" />);
    const initialReads = reads();
    expect(initialReads).toBeGreaterThan(0);

    // Unrelated change (iconId is not a memo dep; layer identity unchanged) —
    // the memo must hold and paint must not be re-read.
    rerender(<LayerTypeIcon layer={layer} iconId="icon-b" />);
    expect(reads()).toBe(initialReads);

    // Keyed change: a NEW paint object must recompute the hints.
    const next = countingPaint();
    rerender(<LayerTypeIcon layer={baseLayer(next.paint)} iconId="icon-b" />);
    expect(next.reads()).toBeGreaterThan(0);
  });

  // The exact regression GUARD-04 exists for: with a NULL layer.paint, keying
  // the memo on the local `paint`/`layout` fallbacks (fresh `{}` per render)
  // would recompute on EVERY render. Count layout reads for a LINE layer
  // (extractStyleHints falls through to layout['line-dasharray'] when paint
  // has none) — the count must not grow on unrelated rerenders.
  it('holds the memo across rerenders when paint is null (fallback-object trap)', () => {
    let layoutReads = 0;
    const layout: Record<string, unknown> = {};
    Object.defineProperty(layout, 'line-dasharray', {
      get() {
        layoutReads += 1;
        return [2, 2];
      },
      enumerable: true,
    });
    const layer: LayerTypeIconLayer = {
      dataset_geometry_type: 'LINESTRING',
      layer_type: 'vector_geolens',
      paint: null as unknown as LayerTypeIconLayer['paint'],
      layout,
      opacity: 1,
      style_config: null,
    };

    const { rerender } = render(<LayerTypeIcon layer={layer} iconId="icon-a" />);
    const initialReads = layoutReads;
    expect(initialReads).toBeGreaterThan(0);

    rerender(<LayerTypeIcon layer={layer} iconId="icon-b" />);
    rerender(<LayerTypeIcon layer={layer} iconId="icon-c" />);
    expect(layoutReads).toBe(initialReads);
  });
});
