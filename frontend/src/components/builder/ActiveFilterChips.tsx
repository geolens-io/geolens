import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';
import {
  NUMERIC_COMPARISON_OPERATORS,
  parseCanonicalFilter,
  type CanonicalFilterCondition,
} from '@/lib/maplibre-filter-utils';

interface ActiveFilterChipsProps {
  layers: MapLayerResponse[];
  onClearFilter: (layerId: string) => void;
}

interface FilterChip {
  layerId: string;
  layerName: string;
  label: string;
}

/**
 * Produce a human-readable summary of a filter expression.
 *
 * builder-audit #338 DRY-01/FILT-01/FILT-02: renders from the single canonical filter
 * parser (parseCanonicalFilter) shared with LayerFilterEditor, so numeric
 * (to-number-wrapped) filters now produce a chip (FILT-01) and the substring
 * "contains" shape is labelled correctly rather than mislabelled as `<value> in
 * (…)` (FILT-02). Opaque/advanced filters intentionally render no chip.
 */
function summarizeFilter(filter: FilterSpecification): string | null {
  const parsed = parseCanonicalFilter(filter);
  if (parsed.kind === 'opaque') return null;

  const parts = parsed.conditions
    .map(summarizeCondition)
    .filter((s): s is string => s !== null);
  if (parts.length === 0) return null;
  if (parts.length === 1) return parts[0];
  const joiner = parsed.combinator === 'all' ? ' & ' : ' | ';
  return parts.join(joiner);
}

function summarizeCondition(c: CanonicalFilterCondition): string | null {
  switch (c.operator) {
    case 'is_null':
      return `${c.field} is null`;
    case 'has':
      return `${c.field} exists`;
    case 'contains':
      return `${c.field} contains "${c.value}"`;
    case 'in_list':
      return `${c.field} in (${previewList(c.listValues)})`;
    case 'not_in_list':
      return `NOT (${c.field} in (${previewList(c.listValues)}))`;
    default:
      if (NUMERIC_COMPARISON_OPERATORS.has(c.operator)) {
        return `${c.field} ${c.operator} ${formatValue(c.rawValue)}`;
      }
      return null;
  }
}

function previewList(values: unknown[] | undefined): string {
  if (!Array.isArray(values)) return '…';
  const preview = values.slice(0, 2).map((v) => String(v)).join(', ');
  return `${preview}${values.length > 2 ? ', …' : ''}`;
}

function formatValue(val: unknown): string {
  if (typeof val === 'string') return `"${val}"`;
  if (val == null) return 'null';
  return String(val);
}

/**
 * Floating filter chips showing active filters for visible layers.
 * Displayed above the map canvas.
 */
export function ActiveFilterChips({ layers, onClearFilter }: ActiveFilterChipsProps) {
  const { t } = useTranslation('builder');

  const chips = useMemo<FilterChip[]>(() => {
    const result: FilterChip[] = [];
    for (const layer of layers) {
      if (!layer.visible || !layer.filter) continue;
      const summary = summarizeFilter(layer.filter);
      if (!summary) continue;
      result.push({
        layerId: layer.id,
        layerName: layer.display_name || layer.dataset_name || t('layers.unnamed'),
        label: summary,
      });
    }
    return result;
  }, [layers, t]);

  if (chips.length === 0) return null;

  return (
    // MAP-20: chips render in PluginHost's top-left anchor (below any top-left
    // plugin, e.g. MeasurementPlugin) and grow downward. max-h-[40vh] +
    // overflow-y-auto caps the column so it does not extend down the left edge
    // into the bottom-left LegendPlugin at ≤800px. See UI-SPEC §Filter-Pill vs
    // floating-plugin Collision Avoidance.
    // WR-01: outer wrapper keeps pointer-events-none for map drag passthrough; inner scroll
    // container restores pointer-events-auto so wheel/touch-scroll events reach the element
    // when the chip list overflows (the case where the cap is actually needed).
    <div className="pointer-events-none">
      <div className="pointer-events-auto flex flex-wrap gap-1.5 max-h-[40vh] overflow-y-auto">
        {chips.map((chip) => (
          <span
            key={chip.layerId}
            className="inline-flex items-center gap-1.5 bg-background/90 backdrop-blur-sm border rounded-full px-2.5 py-1 shadow-sm text-xs"
            title={`${chip.layerName}: ${chip.label}`}
          >
            <span className="font-mono text-2xs uppercase tracking-wider text-muted-foreground">
              {chip.layerName}
            </span>
            <span className="text-foreground">{chip.label}</span>
            <button
              onClick={() => onClearFilter(chip.layerId)}
              className="flex cursor-pointer items-center justify-center h-3.5 w-3.5 rounded-full bg-muted hover:bg-destructive/20 hover:text-destructive text-muted-foreground transition-colors"
              aria-label={t('filters.clear', { defaultValue: 'Clear filter' })}
            >
              <X className="h-2.5 w-2.5" />
            </button>
          </span>
        ))}
      </div>
    </div>
  );
}
