import { describe, expect, it } from 'vitest';
import type { MapBasemapConfig, MapTerrainConfig } from '@/types/api';
import {
  createBuilderBasemapState,
  removeBasemap,
  resetBasemapAppearance,
  resetBasemapSublayer,
  setBasemapLabelsVisible,
  setBasemapBackgroundColor,
  setBasemapMasterOpacity,
  setBasemapPosition,
  setBasemapSublayerOpacity,
  setTerrainExaggeration,
  swapBasemapPreset,
  toggleBasemapSublayerVisibility,
  updateBasemapSublayerOverride,
} from '@/components/builder/basemap-state-controller';
import { BLANK_BASEMAP_ID } from '@/lib/basemap-utils';

const baseConfig: MapBasemapConfig = {
  label_mode: 'full',
  road_visibility: 'full',
  boundary_visibility: 'full',
  building_visibility: true,
  land_water_tone: 'default',
  relief_contrast: null,
  opacity: 1,
  background_color: '#ddeeff',
  basemap_position: 'bottom',
  sublayer_overrides: null,
};

describe('basemap-state-controller', () => {
  it('normalizes basemap state and exposes only persisted editable sublayers', () => {
    const state = createBuilderBasemapState({
      basemapStyle: 'positron',
      showBasemapLabels: true,
      basemapConfig: null,
      terrainConfig: null,
    });

    expect(state.basemapStyle).toBe('openfreemap-positron');
    expect(state.hasVisibleBasemap).toBe(true);
    expect(state.sublayers.map((sublayer) => sublayer.id)).toEqual([
      'basemap:roads',
      'basemap:labels',
      'basemap:buildings',
      'basemap:boundaries',
    ]);
  });

  it('swaps basemap presets while preserving normalized config', () => {
    const state = createBuilderBasemapState({
      basemapStyle: 'openfreemap-positron',
      showBasemapLabels: true,
      basemapConfig: baseConfig,
      terrainConfig: null,
    });

    expect(swapBasemapPreset(state, 'openfreemap-dark')).toMatchObject({
      basemapStyle: 'openfreemap-dark',
      showBasemapLabels: true,
      basemapConfig: expect.objectContaining({ background_color: '#ddeeff' }),
    });
  });

  it('removes the basemap without clearing background color', () => {
    const state = createBuilderBasemapState({
      basemapStyle: 'openfreemap-positron',
      showBasemapLabels: true,
      basemapConfig: baseConfig,
      terrainConfig: null,
    });

    expect(removeBasemap(state)).toMatchObject({
      basemapStyle: BLANK_BASEMAP_ID,
      basemapConfig: expect.objectContaining({ background_color: '#ddeeff' }),
    });
  });

  it('updates background, master opacity, and position through basemap_config', () => {
    const state = createBuilderBasemapState({
      basemapStyle: 'openfreemap-positron',
      showBasemapLabels: true,
      basemapConfig: baseConfig,
      terrainConfig: null,
    });

    expect(setBasemapBackgroundColor(state, '#123456').basemapConfig).toMatchObject({
      background_color: '#123456',
    });
    expect(setBasemapBackgroundColor(state, null).basemapConfig).toMatchObject({
      background_color: null,
    });
    expect(setBasemapMasterOpacity(state, 2).basemapConfig).toMatchObject({ opacity: 1 });
    expect(setBasemapMasterOpacity(state, -1).basemapConfig).toMatchObject({ opacity: 0 });
    expect(setBasemapPosition(state, 'top').basemapConfig).toMatchObject({ basemap_position: 'top' });
  });

  it('routes sublayer visibility through persisted basemap config fields', () => {
    const state = createBuilderBasemapState({
      basemapStyle: 'openfreemap-positron',
      showBasemapLabels: true,
      basemapConfig: baseConfig,
      terrainConfig: null,
    });

    expect(toggleBasemapSublayerVisibility(state, 'basemap:roads').basemapConfig).toMatchObject({
      road_visibility: 'hidden',
    });
    expect(toggleBasemapSublayerVisibility(state, 'basemap:boundaries').basemapConfig).toMatchObject({
      boundary_visibility: 'hidden',
    });
    expect(toggleBasemapSublayerVisibility(state, 'basemap:buildings').basemapConfig).toMatchObject({
      building_visibility: false,
    });
    expect(toggleBasemapSublayerVisibility(state, 'basemap:labels')).toMatchObject({
      showBasemapLabels: false,
      basemapConfig: expect.objectContaining({ label_mode: 'hidden' }),
    });
    expect(setBasemapLabelsVisible(state, false)).toMatchObject({
      showBasemapLabels: false,
      basemapConfig: expect.objectContaining({ label_mode: 'hidden' }),
    });
  });

  it('writes sublayer opacity and style overrides into sublayer_overrides', () => {
    const state = createBuilderBasemapState({
      basemapStyle: 'openfreemap-positron',
      showBasemapLabels: true,
      basemapConfig: baseConfig,
      terrainConfig: null,
    });

    expect(setBasemapSublayerOpacity(state, 'basemap:roads', 0.45).basemapConfig)
      .toMatchObject({ sublayer_overrides: { road: { opacity: 0.45 } } });
    expect(updateBasemapSublayerOverride(state, 'basemap:roads', 'stroke_color', '#ff0000').basemapConfig)
      .toMatchObject({ sublayer_overrides: { road: { stroke_color: '#ff0000' } } });
  });

  it('resets a sublayer override and restores its visibility default', () => {
    const state = createBuilderBasemapState({
      basemapStyle: 'openfreemap-positron',
      showBasemapLabels: false,
      basemapConfig: {
        ...baseConfig,
        label_mode: 'hidden',
        road_visibility: 'hidden',
        sublayer_overrides: {
          road: { opacity: 0.25, stroke_color: '#ff0000' },
          label: { opacity: 0.5 },
        },
      },
      terrainConfig: null,
    });

    expect(resetBasemapSublayer(state, 'basemap:roads').basemapConfig).toMatchObject({
      road_visibility: 'full',
      sublayer_overrides: { label: { opacity: 0.5 } },
    });
    expect(resetBasemapSublayer(state, 'basemap:labels')).toMatchObject({
      showBasemapLabels: true,
      basemapConfig: expect.objectContaining({ label_mode: 'full' }),
    });
  });

  it('resets appearance by clearing local config so state re-normalizes to defaults', () => {
    expect(resetBasemapAppearance()).toEqual({ basemapConfig: null });
  });

  it('clamps terrain exaggeration for existing and new terrain configs', () => {
    const terrain: MapTerrainConfig = {
      enabled: true,
      source_dataset_id: 'dem-1',
      exaggeration: 1,
    };

    expect(setTerrainExaggeration(terrain, 5).terrainConfig).toEqual({
      enabled: true,
      source_dataset_id: 'dem-1',
      exaggeration: 3,
    });
    expect(setTerrainExaggeration(null, -2).terrainConfig).toEqual({
      enabled: false,
      source_dataset_id: null,
      exaggeration: 0,
    });
  });
});
