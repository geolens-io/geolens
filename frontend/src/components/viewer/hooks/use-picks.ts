import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type { WidgetSelection } from '@/components/widgets/contract';
import type { SharedLayerResponse } from '@/types/api';
import {
  fitsAggregateFilterLimits,
  getClusterSourceStrategy,
  serverClusterFilter,
} from '@/components/builder/cluster-source';
import { linkMapLayers, selectionCql2, widgetFilter, type LinkedPick } from '../linked-filters';
import { layerDisplayName } from '../shared-layer';

/** A pick as its filter chip reads, e.g. "land_use: Residential". */
export function pickText(pick: LinkedPick, t: TFunction<'widgets'>): string {
  return t('dashboard.filterChip', { column: pick.selection.column, value: pick.selection.label });
}

type PickFilterProblem = 'too-many-values' | 'clusters-cant-filter' | 'too-many-for-clusters';

const PROBLEM_KEYS = {
  'too-many-values': 'dashboard.tooManyValues',
  'clusters-cant-filter': 'dashboard.clustersCantFilter',
  'too-many-for-clusters': 'dashboard.tooManyForClusters',
} as const satisfies Record<PickFilterProblem, string>;

/**
 * Why `picks` can't all filter `layer`, or null when every transport they feed
 * takes them: the aggregate requests of the layer's widgets, which a widget
 * with no pick of its own sends with the saved filter and every pick, and, on
 * a server-clustered layer, its cluster tile requests. MapLibre and a bounded
 * cluster's GeoJSON filter on the client, without limits.
 */
function pickFilterProblem(layer: SharedLayerResponse, picks: readonly LinkedPick[]): PickFilterProblem | null {
  const onLayer = picks.filter((pick) => pick.layerId === layer.id);
  const { filter } = widgetFilter(layer, onLayer.map((pick) => pick.cql2));
  if (filter && !fitsAggregateFilterLimits(filter)) return 'too-many-values';
  if (getClusterSourceStrategy(layer).kind === 'server-tile') {
    const [linked] = linkMapLayers([layer], onLayer);
    const routed = serverClusterFilter(linked.filter, layer.column_info, layer.dataset_tile_columns);
    if ('omitted' in routed && routed.omitted === 'unsupported') return 'clusters-cant-filter';
    if ('omitted' in routed && routed.omitted === 'too-large') return 'too-many-for-clusters';
  }
  return null;
}

/**
 * The reader's picks as the panel changes them: `choose` sets, replaces or
 * clears a widget's pick, refusing one the server can't filter on, and
 * `remove` clears one from its chip. A pick that any request carrying the
 * layer's filters couldn't take is refused too (`pickFilterProblem`). Each change
 * sets `announcement`, whose `count` changes even when its text repeats.
 */
export function usePicks(
  picks: readonly LinkedPick[],
  onPicksChange: ((picks: readonly LinkedPick[]) => void) | undefined,
  layers: readonly SharedLayerResponse[],
) {
  const { t } = useTranslation('widgets');
  const [announcement, setAnnouncement] = useState({ text: '', count: 0 });
  const announce = (text: string) => setAnnouncement((previous) => ({ text, count: previous.count + 1 }));
  const layerName = (layerId: string) => {
    const layer = layers.find((candidate) => candidate.id === layerId);
    return layer ? layerDisplayName(layer) : '';
  };

  const remove = (pick: LinkedPick) => {
    onPicksChange?.(picks.filter((other) => other.widgetId !== pick.widgetId));
    announce(t('dashboard.filterCleared', { filter: pickText(pick, t), layer: layerName(pick.layerId) }));
  };

  const choose = (widgetId: string, layer: SharedLayerResponse, selection: WidgetSelection | null) => {
    const current = picks.find((pick) => pick.widgetId === widgetId);
    if (selection === null) {
      if (current) remove(current);
      return;
    }
    const cql2 = selectionCql2(layer, selection);
    if (cql2 === null) {
      announce(t('dashboard.cantFilter', { value: selection.label }));
      return;
    }
    const next: LinkedPick = { widgetId, layerId: layer.id, selection, cql2 };
    const nextPicks = current ? picks.map((pick) => (pick === current ? next : pick)) : [...picks, next];
    const problem = pickFilterProblem(layer, nextPicks);
    if (problem) {
      announce(t(PROBLEM_KEYS[problem]));
      return;
    }
    onPicksChange?.(nextPicks);
    announce(t('dashboard.filterApplied', { filter: pickText(next, t), layer: layerDisplayName(layer) }));
  };

  return { choose, remove, announcement, layerName };
}
