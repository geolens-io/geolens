import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type { WidgetSelection } from '@/components/widgets/contract';
import type { SharedLayerResponse } from '@/types/api';
import { fitsClusterFilterLimits, getClusterSourceStrategy } from '@/components/builder/cluster-source';
import { maplibreFilterToCql2 } from '@/lib/maplibre-filter-utils';
import { linkMapLayers, selectionCql2, type LinkedPick } from '../linked-filters';
import { layerDisplayName } from '../shared-layer';

/** A pick as its filter chip reads, e.g. "land_use: Residential". */
export function pickText(pick: LinkedPick, t: TFunction<'widgets'>): string {
  return t('dashboard.filterChip', { column: pick.selection.column, value: pick.selection.label });
}

/**
 * Whether `layer`'s cluster tiles can take its saved filter with `picks` on it.
 * Past the route's limits the map would count every point in its bubbles while
 * the widgets apply the picks.
 */
function clusterTilesCanFilter(layer: SharedLayerResponse, picks: readonly LinkedPick[]): boolean {
  if (getClusterSourceStrategy(layer).kind !== 'server-tile') return true;
  const [linked] = linkMapLayers([layer], picks);
  const cql2 = maplibreFilterToCql2(linked.filter, layer.column_info);
  return !cql2 || cql2 === 'unsupported' || fitsClusterFilterLimits(cql2);
}

/**
 * The reader's picks as the panel changes them: `choose` sets, replaces or
 * clears a widget's pick, refusing one the server can't filter on, and
 * `remove` clears one from its chip. A pick that would push a server-clustered
 * layer's filter past the cluster route's limits is refused too. Each change
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
    if (!clusterTilesCanFilter(layer, nextPicks)) {
      announce(t('dashboard.tooManyForClusters'));
      return;
    }
    onPicksChange?.(nextPicks);
    announce(t('dashboard.filterApplied', { filter: pickText(next, t), layer: layerDisplayName(layer) }));
  };

  return { choose, remove, announcement, layerName };
}
