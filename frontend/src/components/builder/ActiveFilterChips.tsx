import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import type { FilterSpecification } from 'maplibre-gl';
import type { MapLayerResponse } from '@/types/api';

interface ActiveFilterChipsProps {
  layers: MapLayerResponse[];
  onClearFilter: (layerId: string) => void;
}

interface FilterChip {
  layerId: string;
  layerName: string;
  label: string;
}

/** Attempt to produce a human-readable summary of a filter expression. */
function summarizeFilter(filter: FilterSpecification): string | null {
  if (!Array.isArray(filter) || filter.length === 0) return null;

  const op = filter[0];

  // Simple comparison: ["==", ["get", "field"], value]
  if (['==', '!=', '>', '<', '>=', '<='].includes(op) && filter.length === 3) {
    const field = extractField(filter[1]);
    const value = formatValue(filter[2]);
    if (field) return `${field} ${op} ${value}`;
  }

  // "all" / "any" combinator: ["all", cond1, cond2, ...]
  if ((op === 'all' || op === 'any') && filter.length > 1) {
    const parts = filter
      .slice(1)
      .map((c) => summarizeFilter(c as FilterSpecification))
      .filter((s): s is string => s !== null);
    if (parts.length === 0) return null;
    if (parts.length === 1) return parts[0];
    const joiner = op === 'all' ? ' & ' : ' | ';
    return parts.join(joiner);
  }

  // "in" expression: ["in", ["get", "field"], ["literal", [...]]]
  if (op === 'in' && filter.length === 3) {
    const field = extractField(filter[1]);
    if (field) return `${field} in (…)`;
  }

  // "has" expression: ["has", "field"]
  if (op === 'has' && typeof filter[1] === 'string') {
    return `${filter[1]} exists`;
  }

  return null;
}

function extractField(expr: unknown): string | null {
  if (Array.isArray(expr) && expr[0] === 'get' && typeof expr[1] === 'string') {
    return expr[1];
  }
  if (typeof expr === 'string') return expr;
  return null;
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
    <div className="absolute top-12 left-3 right-3 z-10 flex flex-wrap gap-1.5 pointer-events-none">
      {chips.map((chip) => (
        <span
          key={chip.layerId}
          className="pointer-events-auto inline-flex items-center gap-1.5 bg-background/90 backdrop-blur-sm border rounded-full px-2.5 py-1 shadow-sm text-xs"
          title={`${chip.layerName}: ${chip.label}`}
        >
          <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            {chip.layerName}
          </span>
          <span className="text-foreground">{chip.label}</span>
          <button
            onClick={() => onClearFilter(chip.layerId)}
            className="flex items-center justify-center h-3.5 w-3.5 rounded-full bg-muted hover:bg-destructive/20 hover:text-destructive text-muted-foreground transition-colors"
            aria-label={t('filters.clear', { defaultValue: 'Clear filter' })}
          >
            <X className="h-2.5 w-2.5" />
          </button>
        </span>
      ))}
    </div>
  );
}
