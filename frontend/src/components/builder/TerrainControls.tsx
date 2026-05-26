import { AlertTriangle } from 'lucide-react';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import {
  isTerrainCapableDemLayer,
  normalizeTerrainExaggeration,
} from '@/components/builder/map-sync';
import type { MapLayerResponse, MapTerrainConfig } from '@/types/api';

const METER_UNITS = new Set(['m', 'meter', 'meters', 'metre', 'metres']);

interface TerrainControlsProps {
  layers: MapLayerResponse[];
  value: MapTerrainConfig | null;
  onChange: (value: MapTerrainConfig | null) => void;
}

function displayLayerName(layer: MapLayerResponse) {
  return layer.display_name || layer.dataset_name || layer.dataset_table_name;
}

function isMeterUnit(unit: string) {
  return METER_UNITS.has(unit.trim().toLowerCase().replace(/\.$/, ''));
}

function visibleReliefLayerCount(layers: MapLayerResponse[]) {
  return layers.filter((layer) => layer.is_dem === true && layer.visible).length;
}

export function TerrainControls({ layers, value, onChange }: TerrainControlsProps) {
  const { t } = useTranslation('builder');
  const demLayers = useMemo(
    () => layers.filter(isTerrainCapableDemLayer),
    [layers],
  );
  const reliefCount = useMemo(() => visibleReliefLayerCount(layers), [layers]);
  const hasDemLayers = demLayers.length > 0;
  const configuredSourceId = value?.source_dataset_id ?? null;
  const selectedSourceId = configuredSourceId && demLayers.some((layer) => layer.dataset_id === configuredSourceId)
    ? configuredSourceId
    : demLayers[0]?.dataset_id ?? null;
  const selectedLayer = selectedSourceId
    ? demLayers.find((layer) => layer.dataset_id === selectedSourceId) ?? null
    : null;
  const enabled = !!value?.enabled && hasDemLayers;
  const exaggeration = normalizeTerrainExaggeration(value?.exaggeration);

  const unitWarning = selectedLayer
    ? selectedLayer.dem_vertical_units
      ? isMeterUnit(selectedLayer.dem_vertical_units)
        ? null
        : t('terrain.unitsNonMeter', {
          unit: selectedLayer.dem_vertical_units,
          defaultValue: 'Vertical units are {{unit}}, not meters; terrain scale is approximate.',
        })
      : t('terrain.unitsUnknown', {
        defaultValue: 'Vertical units are unavailable; terrain scale is approximate.',
      })
    : null;

  function nextConfig(partial: Partial<MapTerrainConfig>): MapTerrainConfig {
    return {
      enabled,
      source_dataset_id: selectedSourceId,
      exaggeration,
      ...partial,
    };
  }

  function handleEnabledChange(checked: boolean) {
    if (!hasDemLayers) return;
    onChange(nextConfig({
      enabled: checked,
      source_dataset_id: selectedSourceId ?? demLayers[0]?.dataset_id ?? null,
    }));
  }

  function handleSourceChange(sourceDatasetId: string) {
    onChange(nextConfig({ source_dataset_id: sourceDatasetId }));
  }

  return (
    <div className="space-y-3 px-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <Label htmlFor="terrain-enabled" className="text-sm font-medium">
            {t('terrain.surfaceTitle', { defaultValue: 'Elevation surface' })}
          </Label>
          <p className="mt-0.5 text-xs leading-snug text-muted-foreground">
            {t('terrain.surfaceDescription', {
              defaultValue: 'Terrain drapes the map surface; Relief layers provide visible shading.',
            })}
          </p>
        </div>
        <Switch
          id="terrain-enabled"
          size="sm"
          checked={enabled}
          disabled={!hasDemLayers}
          onCheckedChange={handleEnabledChange}
          aria-label={t('terrain.enabled', { defaultValue: 'Enable terrain' })}
        />
      </div>

      {!hasDemLayers ? (
        <p className="text-xs text-muted-foreground">
          {t('terrain.noDem', { defaultValue: 'Add a DEM raster layer to enable terrain.' })}
        </p>
      ) : (
        <>
          <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 rounded-md border border-border/60 bg-muted/30 p-2 text-xs">
            <dt className="text-muted-foreground">
              {t('terrain.selectedDem', { defaultValue: 'Selected DEM' })}
            </dt>
            <dd className="max-w-32 truncate text-right font-medium text-foreground" title={selectedLayer ? displayLayerName(selectedLayer) : undefined}>
              {selectedLayer ? displayLayerName(selectedLayer) : t('terrain.noSource', { defaultValue: 'None' })}
            </dd>
            <dt className="text-muted-foreground">
              {t('terrain.visualRelief', { defaultValue: 'Visual relief' })}
            </dt>
            <dd className="text-right font-medium text-foreground">
              {reliefCount > 0
                ? t('terrain.reliefLayerCount', {
                  count: reliefCount,
                  defaultValue: reliefCount === 1 ? '{{count}} visible DEM layer' : '{{count}} visible DEM layers',
                })
                : t('terrain.noReliefLayer', { defaultValue: 'No visible relief layer' })}
            </dd>
          </dl>

          <div className="space-y-1.5">
            <Label htmlFor="terrain-source" className="text-xs text-muted-foreground">
              {t('terrain.source', { defaultValue: 'DEM source' })}
            </Label>
            <Select
              value={selectedSourceId ?? undefined}
              onValueChange={handleSourceChange}
            >
              <SelectTrigger id="terrain-source" className="h-8 text-xs">
                <SelectValue placeholder={t('terrain.sourcePlaceholder', { defaultValue: 'Select DEM' })} />
              </SelectTrigger>
              <SelectContent>
                {demLayers.map((layer) => (
                  <SelectItem key={layer.dataset_id} value={layer.dataset_id} className="text-xs">
                    {displayLayerName(layer)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {unitWarning && (
            <div className="flex items-start gap-2 rounded bg-warning/15 p-2">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning-foreground" />
              <span className="text-xs leading-snug text-warning-foreground">{unitWarning}</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
