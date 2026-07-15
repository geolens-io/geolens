import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Filter, X } from 'lucide-react';
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
  const [open, setOpen] = useState(false);

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
    // The chips share PluginHost's top-left anchor with the MapLibre
    // NavigationControl (index.css pins it at margin-top 32px / left 10px,
    // ~29px wide) and the MapCoordReadout pill. Collapsing to a summary pill +
    // `ml-12` (clears the zoom control) keeps both usable — the old always-open
    // chip stack rendered straight over them. max-h-[40vh] + overflow-y-auto
    // caps the expanded column so it cannot run down into the bottom-left
    // LegendPlugin. WR-01: outer wrapper stays pointer-events-none for map-drag
    // passthrough; the inner column restores pointer-events-auto for scroll.
    <div className="pointer-events-none ml-12">
      <div className="pointer-events-auto flex max-h-[40vh] flex-col items-start gap-1.5 overflow-y-auto">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={t('filters.toggle', { defaultValue: 'Show or hide active filters' })}
          className="inline-flex items-center gap-1.5 rounded-md border bg-background/90 px-2.5 py-1 text-xs shadow-sm backdrop-blur-sm transition-colors hover:bg-accent"
        >
          <Filter className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
          <span className="font-medium text-foreground">
            {t('filters.title', { defaultValue: 'Filters' })}
          </span>
          <span className="flex min-w-4 items-center justify-center rounded-full bg-primary/15 px-1 font-mono text-2xs font-semibold text-primary">
            {chips.length}
          </span>
        </button>

        {open &&
          chips.map((chip) => (
            <span
              key={chip.layerId}
              className="inline-flex items-center gap-1.5 rounded-md border bg-background/90 px-2.5 py-1 text-xs shadow-sm backdrop-blur-sm"
              title={`${chip.layerName}: ${chip.label}`}
            >
              <span className="font-mono text-2xs uppercase tracking-wider text-muted-foreground">
                {chip.layerName}
              </span>
              <span className="text-foreground">{chip.label}</span>
              <button
                type="button"
                onClick={() => onClearFilter(chip.layerId)}
                className="flex h-3.5 w-3.5 cursor-pointer items-center justify-center rounded-full bg-muted text-muted-foreground transition-colors hover:bg-destructive/20 hover:text-destructive"
                aria-label={t('filters.clear', { defaultValue: 'Clear filter' })}
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}

        {open && chips.length > 1 && (
          <button
            type="button"
            onClick={() => chips.forEach((chip) => onClearFilter(chip.layerId))}
            className="rounded-md border bg-background/90 px-2.5 py-1 text-2xs font-medium uppercase tracking-wider text-muted-foreground shadow-sm backdrop-blur-sm transition-colors hover:text-destructive"
          >
            {t('filters.clearAll', { defaultValue: 'Clear all' })}
          </button>
        )}
      </div>
    </div>
  );
}
