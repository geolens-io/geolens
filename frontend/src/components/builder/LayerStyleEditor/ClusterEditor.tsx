import { Plus, Trash2 } from 'lucide-react';
import { StyleColorPicker, SwatchColorPopover } from '../StyleColorPicker';
import { SliderRow } from '../HeatmapStyleControls';
import { CIRCLE_DEFAULTS } from './utils';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MAP_COLORS } from '@/lib/map-colors';
import type { BaseStyleEditorProps } from './types';

type ClusterColorStop = { count: number; color: string };

// Default tiers seeded when "color by cluster size" is enabled. MapLibre's own
// "create and style clusters" example uses 100/750, but those thresholds are
// tuned to its dense earthquake dataset — for typical clustered layers the
// rendered cluster point_count at usable zooms sits in the 1s–low-100s, so
// 100/750 leaves every cluster in the base bucket and the toggle looks dead
// (a few-thousand-point layer tops out around a couple hundred per cluster at
// min zoom, dropping into the low tens by the default view).
// Seed reachable breaks so enabling the ramp produces a visible gradient out of
// the box; the user can raise them for denser data.
// Ramp seeds trace to the shared categorical palette (amber -> pink).
const DEFAULT_RAMP_TIERS: ClusterColorStop[] = [
  { count: 10, color: MAP_COLORS.categorical[6] },
  { count: 50, color: MAP_COLORS.categorical[5] },
];

export function ClusterEditor({
  paint,
  builderConfig,
  onBuilderChange,
  t,
}: BaseStyleEditorProps) {
  const clusterColor = builderConfig.clusterColor
    ?? (typeof paint['circle-color'] === 'string' ? paint['circle-color'] as string : CIRCLE_DEFAULTS['circle-color']);
  const clusterTextColor = builderConfig.clusterTextColor ?? MAP_COLORS.cluster.text;

  const ramp: ClusterColorStop[] = Array.isArray(builderConfig.clusterColorRamp)
    ? builderConfig.clusterColorRamp
    : [];
  // A ramp needs a base + at least one threshold (2+ stops) to color by count;
  // anything less falls back to the flat clusterColor.
  const rampActive = ramp.length >= 2;

  // Empty array (not undefined) disables the ramp without relying on builder
  // field-deletion semantics — the adapter reads length < 2 as "flat color".
  const setRamp = (next: ClusterColorStop[]) => onBuilderChange({ clusterColorRamp: next });

  const toggleRamp = (on: boolean) => {
    setRamp(on ? [{ count: 0, color: clusterColor }, ...DEFAULT_RAMP_TIERS] : []);
  };

  const updateStop = (index: number, patch: Partial<ClusterColorStop>) =>
    setRamp(ramp.map((stop, i) => (i === index ? { ...stop, ...patch } : stop)));

  const addStop = () => {
    const last = ramp[ramp.length - 1];
    setRamp([...ramp, { count: (last?.count ?? 0) + 250, color: clusterColor }]);
  };

  const removeStop = (index: number) => {
    const next = ramp.filter((_, i) => i !== index);
    // Drop below 2 stops → revert to flat color.
    setRamp(next.length >= 2 ? next : []);
  };

  return (
    <div className="space-y-3">
      <SliderRow
        label={t('style.cluster.radius')}
        value={builderConfig.clusterRadius ?? 48}
        min={1}
        max={120}
        step={1}
        format="px"
        onChange={(val) => onBuilderChange({ clusterRadius: val })}
      />
      <SliderRow
        label={t('style.cluster.maxZoom')}
        value={builderConfig.clusterMaxZoom ?? 14}
        min={0}
        max={22}
        step={1}
        format="zoom"
        onChange={(val) => onBuilderChange({ clusterMaxZoom: val })}
      />

      <div className="flex items-center justify-between">
        <Label htmlFor="cluster-color-by-count" className="text-sm font-normal">
          {t('style.cluster.colorByCount')}
        </Label>
        <Switch
          id="cluster-color-by-count"
          checked={rampActive}
          onCheckedChange={toggleRamp}
        />
      </div>

      {rampActive ? (
        <div className="space-y-2">
          <StyleColorPicker
            label={t('style.cluster.baseColor')}
            color={ramp[0].color}
            onChange={(hex) => updateStop(0, { color: hex })}
          />
          {ramp.slice(1).map((stop, i) => {
            const index = i + 1;
            return (
              <div key={index} className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-20">{t('style.cluster.atCount')}</span>
                <Input
                  type="number"
                  min={1}
                  value={stop.count}
                  onChange={(e) => updateStop(index, { count: Number(e.target.value) })}
                  className="h-7 w-20"
                  aria-label={`${t('style.cluster.atCount')} ${index}`}
                />
                <SwatchColorPopover
                  color={stop.color}
                  onChange={(hex) => updateStop(index, { color: hex })}
                  label={`${t('style.cluster.colorByCount')} ${index}`}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 ms-auto"
                  onClick={() => removeStop(index)}
                  aria-label={t('style.cluster.removeStop')}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            );
          })}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full"
            onClick={addStop}
          >
            <Plus className="me-1 h-4 w-4" />
            {t('style.cluster.addStop')}
          </Button>
        </div>
      ) : (
        <StyleColorPicker
          label={t('style.cluster.color')}
          color={clusterColor}
          onChange={(hex) => onBuilderChange({ clusterColor: hex })}
        />
      )}

      <StyleColorPicker
        label={t('style.cluster.countColor')}
        color={clusterTextColor}
        onChange={(hex) => onBuilderChange({ clusterTextColor: hex })}
      />
      <SliderRow
        label={t('style.cluster.countSize')}
        value={builderConfig.clusterTextSize ?? 12}
        min={8}
        max={24}
        step={1}
        format="px"
        onChange={(val) => onBuilderChange({ clusterTextSize: val })}
      />
    </div>
  );
}

export default ClusterEditor;
