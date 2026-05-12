import { describe, expect, it } from 'vitest';
import {
  RENDER_AS_WRITABLE_FIELDS,
  RENDERER_CAPABILITIES,
  UNSUPPORTED_V1002_RENDERERS,
  buildRenderAsPatch,
  getCurrentRenderAs,
  getRenderAsOptions,
  getRendererCapabilities,
  getRendererCapability,
  getRenderAsSource,
  isSupportedRenderAsId,
} from '../renderAs';
import type { MapLayerResponse, StyleConfig } from '@/types/api';

function layer(overrides: Partial<MapLayerResponse> = {}): MapLayerResponse {
  return {
    id: overrides.id ?? 'layer-1',
    dataset_id: overrides.dataset_id ?? 'dataset-1',
    dataset_name: overrides.dataset_name ?? 'Dataset',
    dataset_geometry_type: overrides.dataset_geometry_type ?? 'POINT',
    dataset_table_name: overrides.dataset_table_name ?? 'dataset',
    dataset_extent_bbox: null,
    dataset_column_info: null,
    dataset_feature_count: null,
    dataset_sample_values: null,
    display_name: null,
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: overrides.paint ?? {},
    layout: overrides.layout ?? {},
    filter: null,
    label_config: null,
    popup_config: null,
    style_config: overrides.style_config ?? null,
    layer_type: overrides.layer_type ?? 'vector_geolens',
    dataset_record_type: overrides.dataset_record_type ?? 'vector_dataset',
    show_in_legend: true,
    is_3d: overrides.is_3d ?? null,
    is_dem: overrides.is_dem ?? false,
    dem_vertical_units: null,
    ...overrides,
  };
}

function optionIds(input: MapLayerResponse) {
  return getRenderAsOptions(input).map((option) => option.id);
}

describe('renderAs view model', () => {
  it('offers point, symbol, and heatmap for point vector layers', () => {
    const point = layer({ dataset_geometry_type: 'MULTIPOINT' });

    expect(getRenderAsSource(point)).toBe('vector-point');
    expect(optionIds(point)).toEqual(['point', 'symbol', 'heatmap']);
    expect(getCurrentRenderAs(point)).toBe('point');
  });

  it('offers cluster for bounded and large point vector layers with feature count metadata', () => {
    const boundedPoint = layer({
      dataset_geometry_type: 'MULTIPOINT',
      dataset_feature_count: 250,
    });
    const largePoint = layer({
      dataset_geometry_type: 'POINT',
      dataset_feature_count: 5001,
    });

    expect(optionIds(boundedPoint)).toEqual(['point', 'symbol', 'heatmap', 'cluster']);
    expect(optionIds(largePoint)).toEqual(['point', 'symbol', 'heatmap', 'cluster']);
  });

  it('detects point symbol and heatmap render modes from style_config', () => {
    expect(getCurrentRenderAs(layer({
      style_config: { render_mode: 'symbol' } as StyleConfig,
    }))).toBe('symbol');
    expect(getCurrentRenderAs(layer({
      style_config: { render_mode: 'heatmap' } as StyleConfig,
    }))).toBe('heatmap');
    expect(getCurrentRenderAs(layer({
      dataset_feature_count: 25,
      style_config: { render_mode: 'cluster' } as StyleConfig,
    }))).toBe('cluster');
    expect(getCurrentRenderAs(layer({
      dataset_feature_count: 10_000,
      style_config: { render_mode: 'cluster' } as StyleConfig,
    }))).toBe('cluster');
  });

  it('offers line and arrow for line layers', () => {
    const line = layer({ dataset_geometry_type: 'MULTILINESTRING' });

    expect(getRenderAsSource(line)).toBe('vector-line');
    expect(optionIds(line)).toEqual(['line', 'arrow']);
    expect(getCurrentRenderAs(line)).toBe('line');
  });

  it('documents line arrow as a MapLibre companion renderer capability', () => {
    const line = layer({ dataset_geometry_type: 'MULTILINESTRING' });
    const capabilities = getRendererCapabilities(line);
    const arrow = getRendererCapability('arrow', line);

    expect(RENDERER_CAPABILITIES.length).toBeGreaterThan(0);
    expect(capabilities.map((entry) => entry.id)).toEqual(['line', 'arrow']);
    expect(arrow).toMatchObject({
      id: 'arrow',
      backend: 'maplibre',
      sourceRequirement: 'vector-tile',
      companionLayers: ['arrow'],
      viewerSupport: 'native',
      styleJsonSupport: 'native',
    });
    expect(arrow?.writableFields).toEqual(RENDER_AS_WRITABLE_FIELDS);
  });

  it('documents point cluster as a bounded GeoJSON renderer capability', () => {
    const point = layer({ dataset_geometry_type: 'POINT', dataset_feature_count: 100 });
    const cluster = getRendererCapability('cluster', point);

    expect(getRendererCapabilities(point).map((entry) => entry.id)).toEqual(['point', 'symbol', 'heatmap', 'cluster']);
    expect(cluster).toMatchObject({
      id: 'cluster',
      backend: 'maplibre',
      sourceRequirement: 'geojson-or-cluster-tile',
      companionLayers: ['cluster', 'cluster-count', 'unclustered'],
      viewerSupport: 'native',
      styleJsonSupport: 'fallback',
      requiresClusterSource: true,
    });
    expect(cluster?.writableFields).toEqual(RENDER_AS_WRITABLE_FIELDS);
  });

  it('detects line arrow render mode from style_config', () => {
    expect(getCurrentRenderAs(layer({
      dataset_geometry_type: 'LINESTRING',
      style_config: { render_mode: 'arrow' } as StyleConfig,
    }))).toBe('arrow');
  });

  it('offers existing polygon fill, stroke, fill-stroke, and extrusion renderings', () => {
    const polygon = layer({ dataset_geometry_type: 'MULTIPOLYGON' });

    expect(getRenderAsSource(polygon)).toBe('vector-polygon');
    expect(optionIds(polygon)).toEqual(['fill', 'stroke', 'fill-stroke', 'extrusion-3d']);
    expect(getCurrentRenderAs(polygon)).toBe('fill-stroke');
  });

  it('detects polygon stroke, fill, and extrusion from existing builder metadata', () => {
    expect(getCurrentRenderAs(layer({
      dataset_geometry_type: 'POLYGON',
      style_config: { builder: { fillDisabled: true } } as StyleConfig,
    }))).toBe('stroke');

    expect(getCurrentRenderAs(layer({
      dataset_geometry_type: 'POLYGON',
      style_config: { builder: { strokeDisabled: true } } as StyleConfig,
    }))).toBe('fill');

    expect(getCurrentRenderAs(layer({
      dataset_geometry_type: 'POLYGON',
      style_config: { builder: { heightColumn: 'height_m' } } as StyleConfig,
    }))).toBe('extrusion-3d');
  });

  it('offers image for raster layers and image plus hillshade for DEM rasters', () => {
    const raster = layer({
      dataset_geometry_type: null,
      dataset_record_type: 'raster_dataset',
      layer_type: 'raster_geolens',
      is_dem: false,
    });
    const dem = layer({
      dataset_geometry_type: null,
      dataset_record_type: 'raster_dataset',
      layer_type: 'raster_geolens',
      is_dem: true,
    });

    expect(getRenderAsSource(raster)).toBe('raster');
    expect(optionIds(raster)).toEqual(['image']);
    expect(getCurrentRenderAs(raster)).toBe('image');

    expect(getRenderAsSource(dem)).toBe('raster-dem');
    expect(optionIds(dem)).toEqual(['image', 'hillshade']);
    expect(getCurrentRenderAs({
      ...dem,
      style_config: { render_mode: 'hillshade' } as StyleConfig,
    })).toBe('hillshade');
  });

  it('returns no renderAs options for unsupported non-spatial table layers', () => {
    const table = layer({
      dataset_geometry_type: null,
      dataset_record_type: 'table',
    });

    expect(getRenderAsSource(table)).toBe('unsupported');
    expect(getRenderAsOptions(table)).toEqual([]);
    expect(getCurrentRenderAs(table)).toBeNull();
  });

  it('does not expose punted v1002 renderers', () => {
    for (const renderer of UNSUPPORTED_V1002_RENDERERS) {
      expect(isSupportedRenderAsId(renderer)).toBe(false);
    }
    expect(isSupportedRenderAsId('cluster')).toBe(true);

    const allOptionIds = [
      ...optionIds(layer({ dataset_geometry_type: 'POINT' })),
      ...optionIds(layer({ dataset_geometry_type: 'LINESTRING' })),
      ...optionIds(layer({ dataset_geometry_type: 'POLYGON' })),
      ...optionIds(layer({ dataset_geometry_type: null, dataset_record_type: 'raster_dataset', layer_type: 'raster_geolens' })),
      ...optionIds(layer({ dataset_geometry_type: null, dataset_record_type: 'raster_dataset', layer_type: 'raster_geolens', is_dem: true })),
    ];

    expect(allOptionIds).not.toEqual(expect.arrayContaining([...UNSUPPORTED_V1002_RENDERERS]));
  });

  it('documents writable fields without including is_3d', () => {
    expect(RENDER_AS_WRITABLE_FIELDS).toEqual(['layer_type', 'style_config', 'paint', 'layout']);
    expect(RENDER_AS_WRITABLE_FIELDS).not.toContain('is_3d');
    expect(JSON.stringify(getRenderAsOptions(layer({ is_3d: true })))).not.toContain('is_3d');
  });

  it('builds point renderAs patches using only existing writable fields', () => {
    const mutation = buildRenderAsPatch(layer({ dataset_geometry_type: 'POINT' }), 'heatmap');

    expect(mutation?.adapterType).toBe('heatmap');
    expect(mutation?.patch).toEqual(expect.objectContaining({
      layer_type: 'vector_geolens',
      paint: expect.objectContaining({ 'heatmap-opacity': 0.8 }),
      style_config: expect.objectContaining({ render_mode: 'heatmap' }),
    }));
    for (const key of Object.keys(mutation?.patch ?? {})) {
      expect(RENDER_AS_WRITABLE_FIELDS).toContain(key);
    }
    expect(JSON.stringify(mutation?.patch)).not.toContain('is_3d');
  });

  it('builds cluster patches using only existing writable fields for eligible point layers', () => {
    const mutation = buildRenderAsPatch(layer({
      dataset_geometry_type: 'POINT',
      dataset_feature_count: 100,
      paint: { 'circle-color': '#2255aa', 'circle-radius': 6 },
    }), 'cluster');

    expect(mutation?.adapterType).toBe('circle');
    expect(mutation?.patch).toEqual(expect.objectContaining({
      layer_type: 'vector_geolens',
      paint: expect.objectContaining({ 'circle-color': '#2255aa' }),
      style_config: expect.objectContaining({
        render_mode: 'cluster',
        builder: expect.objectContaining({
          clusterRadius: 48,
          clusterMaxZoom: 14,
          clusterColor: '#2255aa',
          clusterTextColor: '#ffffff',
          clusterTextSize: 12,
        }),
      }),
    }));
    for (const key of Object.keys(mutation?.patch ?? {})) {
      expect(RENDER_AS_WRITABLE_FIELDS).toContain(key);
    }
    expect(JSON.stringify(mutation?.patch)).not.toContain('is_3d');
    expect(buildRenderAsPatch(layer({ dataset_geometry_type: 'POINT', dataset_feature_count: 6000 }), 'cluster')).toEqual(
      expect.objectContaining({
        patch: expect.objectContaining({
          style_config: expect.objectContaining({ render_mode: 'cluster' }),
        }),
      }),
    );
  });

  it('builds polygon fill, stroke, and 3D extrusion patches without is_3d', () => {
    const polygon = layer({
      dataset_geometry_type: 'POLYGON',
      dataset_column_info: [{ name: 'height_m', type: 'double precision' }],
    });

    expect(buildRenderAsPatch(polygon, 'stroke')?.patch.style_config?.builder).toEqual(expect.objectContaining({
      fillDisabled: true,
      strokeDisabled: false,
    }));

    const extrusion = buildRenderAsPatch(polygon, 'extrusion-3d');
    expect(extrusion?.adapterType).toBe('fill');
    expect(extrusion?.patch.style_config?.builder).toEqual(expect.objectContaining({
      fillDisabled: false,
      strokeDisabled: false,
      heightColumn: 'height_m',
      heightScale: 1,
      extrusionMinZoom: 14,
      extrusionOpacity: 0.85,
    }));
    expect(JSON.stringify(extrusion?.patch)).not.toContain('is_3d');
  });

  it('builds line arrow patches using only existing writable fields', () => {
    const line = layer({
      dataset_geometry_type: 'LINESTRING',
      paint: { 'line-color': '#2255aa', 'line-width': 3 },
    });

    const mutation = buildRenderAsPatch(line, 'arrow');

    expect(mutation?.adapterType).toBe('line');
    expect(mutation?.patch).toEqual(expect.objectContaining({
      layer_type: 'vector_geolens',
      style_config: expect.objectContaining({
        render_mode: 'arrow',
        builder: expect.objectContaining({
          arrowColor: '#2255aa',
          arrowSize: 14,
          arrowSpacing: 80,
        }),
      }),
    }));
    for (const key of Object.keys(mutation?.patch ?? {})) {
      expect(RENDER_AS_WRITABLE_FIELDS).toContain(key);
    }
    expect(JSON.stringify(mutation?.patch)).not.toContain('is_3d');
  });

  it('clears line arrow builder state when switching back to plain line', () => {
    const mutation = buildRenderAsPatch(layer({
      dataset_geometry_type: 'LINESTRING',
      style_config: {
        render_mode: 'arrow',
        builder: {
          arrowColor: '#2255aa',
          arrowSize: 18,
          arrowSpacing: 120,
          lineGradient: { stops: [] },
        },
      } as unknown as StyleConfig,
    }), 'line');

    expect(mutation?.adapterType).toBe('line');
    expect(mutation?.patch.style_config?.render_mode).toBeUndefined();
    expect(mutation?.patch.style_config?.builder).toEqual({
      lineGradient: { stops: [] },
    });
  });

  it('builds raster DEM image and hillshade patches', () => {
    const dem = layer({
      dataset_geometry_type: null,
      dataset_record_type: 'raster_dataset',
      layer_type: 'raster_geolens',
      is_dem: true,
    });

    expect(buildRenderAsPatch(dem, 'image')).toMatchObject({
      adapterType: 'raster',
      patch: {
        layer_type: 'raster_geolens',
      },
    });
    expect(buildRenderAsPatch(dem, 'hillshade')).toMatchObject({
      adapterType: 'hillshade',
      patch: {
        layer_type: 'raster_geolens',
        style_config: { render_mode: 'hillshade' },
      },
    });
  });

  it('rejects unsupported renderAs mutations for a source', () => {
    expect(buildRenderAsPatch(layer({ dataset_geometry_type: 'LINESTRING' }), 'heatmap')).toBeNull();
    expect(buildRenderAsPatch(layer({ dataset_geometry_type: null, dataset_record_type: 'table' }), 'fill')).toBeNull();
  });
});
