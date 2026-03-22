import { getLayerCapabilities } from '../layer-capabilities';

describe('getLayerCapabilities', () => {
  it('returns raster capabilities for raster_geolens + raster_dataset', () => {
    const caps = getLayerCapabilities({
      layer_type: 'raster_geolens',
      dataset_record_type: 'raster_dataset',
      dataset_geometry_type: null,
    });
    expect(caps).toEqual({
      kind: 'raster',
      supportsStyleEditor: false,
      supportsFilterEditor: false,
      supportsLabelEditor: false,
      supportsOpacity: true,
      mapLayerType: 'raster',
      iconVariant: 'raster',
    });
  });

  it('returns vrt capabilities for raster_geolens + vrt_dataset', () => {
    const caps = getLayerCapabilities({
      layer_type: 'raster_geolens',
      dataset_record_type: 'vrt_dataset',
      dataset_geometry_type: null,
    });
    expect(caps).toEqual({
      kind: 'vrt',
      supportsStyleEditor: false,
      supportsFilterEditor: false,
      supportsLabelEditor: false,
      supportsOpacity: true,
      mapLayerType: 'raster',
      iconVariant: 'vrt',
    });
  });

  it('returns circle vector capabilities for POINT geometry', () => {
    const caps = getLayerCapabilities({
      layer_type: 'vector_geolens',
      dataset_record_type: undefined,
      dataset_geometry_type: 'POINT',
    });
    expect(caps).toEqual({
      kind: 'vector',
      supportsStyleEditor: true,
      supportsFilterEditor: true,
      supportsLabelEditor: true,
      supportsOpacity: true,
      mapLayerType: 'circle',
      iconVariant: 'point',
    });
  });

  it('returns line vector capabilities for LINESTRING geometry', () => {
    const caps = getLayerCapabilities({
      layer_type: 'vector_geolens',
      dataset_record_type: undefined,
      dataset_geometry_type: 'LINESTRING',
    });
    expect(caps).toEqual({
      kind: 'vector',
      supportsStyleEditor: true,
      supportsFilterEditor: true,
      supportsLabelEditor: true,
      supportsOpacity: true,
      mapLayerType: 'line',
      iconVariant: 'line',
    });
  });

  it('returns fill vector capabilities for POLYGON geometry', () => {
    const caps = getLayerCapabilities({
      layer_type: 'vector_geolens',
      dataset_record_type: undefined,
      dataset_geometry_type: 'POLYGON',
    });
    expect(caps).toEqual({
      kind: 'vector',
      supportsStyleEditor: true,
      supportsFilterEditor: true,
      supportsLabelEditor: true,
      supportsOpacity: true,
      mapLayerType: 'fill',
      iconVariant: 'polygon',
    });
  });

  it('returns circle for MULTIPOINT geometry (MULTI prefix handled)', () => {
    const caps = getLayerCapabilities({
      layer_type: 'vector_geolens',
      dataset_record_type: undefined,
      dataset_geometry_type: 'MULTIPOINT',
    });
    expect(caps.mapLayerType).toBe('circle');
  });

  it('defaults to fill/polygon for null geometry type', () => {
    const caps = getLayerCapabilities({
      layer_type: 'vector_geolens',
      dataset_record_type: undefined,
      dataset_geometry_type: null,
    });
    expect(caps.mapLayerType).toBe('fill');
    expect(caps.iconVariant).toBe('polygon');
  });

  it('VRT classified as raster at map layer level', () => {
    const caps = getLayerCapabilities({
      layer_type: 'raster_geolens',
      dataset_record_type: 'vrt_dataset',
      dataset_geometry_type: null,
    });
    expect(caps.mapLayerType).toBe('raster');
  });

  it('all raster-like kinds disable style/filter/label editors', () => {
    for (const recordType of ['raster_dataset', 'vrt_dataset']) {
      const caps = getLayerCapabilities({
        layer_type: 'raster_geolens',
        dataset_record_type: recordType,
        dataset_geometry_type: null,
      });
      expect(caps.supportsStyleEditor).toBe(false);
      expect(caps.supportsFilterEditor).toBe(false);
      expect(caps.supportsLabelEditor).toBe(false);
    }
  });

  it('all vector kinds enable all editors', () => {
    for (const geomType of ['POINT', 'LINESTRING', 'POLYGON', 'MULTIPOLYGON']) {
      const caps = getLayerCapabilities({
        layer_type: 'vector_geolens',
        dataset_record_type: undefined,
        dataset_geometry_type: geomType,
      });
      expect(caps.supportsStyleEditor).toBe(true);
      expect(caps.supportsFilterEditor).toBe(true);
      expect(caps.supportsLabelEditor).toBe(true);
    }
  });

  it('VRT and raster differ only in kind and iconVariant', () => {
    const raster = getLayerCapabilities({
      layer_type: 'raster_geolens',
      dataset_record_type: 'raster_dataset',
      dataset_geometry_type: null,
    });
    const vrt = getLayerCapabilities({
      layer_type: 'raster_geolens',
      dataset_record_type: 'vrt_dataset',
      dataset_geometry_type: null,
    });
    expect(raster.kind).not.toBe(vrt.kind);
    expect(raster.iconVariant).not.toBe(vrt.iconVariant);
    expect(raster.mapLayerType).toBe(vrt.mapLayerType);
    expect(raster.supportsOpacity).toBe(vrt.supportsOpacity);
    expect(raster.supportsStyleEditor).toBe(vrt.supportsStyleEditor);
  });

  it('GEOMETRYCOLLECTION defaults to fill/polygon', () => {
    const caps = getLayerCapabilities({
      layer_type: 'vector_geolens',
      dataset_record_type: undefined,
      dataset_geometry_type: 'GEOMETRYCOLLECTION',
    });
    expect(caps.mapLayerType).toBe('fill');
  });
});
