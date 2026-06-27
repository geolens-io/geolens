import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { ColorizedGeometryIcon } from '../layer-icons';

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
