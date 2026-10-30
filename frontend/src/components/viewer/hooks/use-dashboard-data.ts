import { useEffect, useMemo, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { fetchAggregate, type AggregateRequest } from '@/api/aggregate';
import type { AnyWidgetDefinition, WidgetInstance } from '@/components/widgets/contract';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { wrapBboxLongitudes, type Bbox } from '@/lib/bbox';
import { queryKeys } from '@/lib/query-keys';
import type { SharedLayerResponse } from '@/types/api';
import type { Cql2Expression } from '@/lib/maplibre-filter-utils';
import { NO_PICKS, widgetFilter } from '../linked-filters';

/** How long the map must rest before view-scoped widgets refetch. */
export const VIEW_REFETCH_DEBOUNCE_MS = 400;

// About a metre; a sub-pixel move keeps the same bbox, and so the cached aggregate.
const round = (value: number) => Math.round(value * 1e5) / 1e5;

export function mapViewBbox(map: MaplibreMap): Bbox {
  const bounds = map.getBounds();
  // getBounds() runs past +/-180 on world copies.
  return wrapBboxLongitudes([
    bounds.getWest(),
    bounds.getSouth(),
    bounds.getEast(),
    bounds.getNorth(),
  ]).map(round) as Bbox;
}

const sameBbox = (a: Bbox, b: Bbox) => a.every((value, index) => value === b[index]);

/**
 * The map's view as a bbox once the map has rested for
 * `VIEW_REFETCH_DEBOUNCE_MS`, the first read included, so a view the map
 * leaves at once (a fit on load) is never asked for. Null until then and
 * while disabled; a caller that unmounts on collapse starts from null again.
 */
export function useMapViewBbox(map: MaplibreMap | null, enabled: boolean): Bbox | null {
  const [bbox, setBbox] = useState<Bbox | null>(null);
  useEffect(() => {
    if (!map || !enabled) {
      setBbox(null);
      return;
    }
    const read = () => {
      const next = mapViewBbox(map);
      setBbox((prev) => (prev && sameBbox(prev, next) ? prev : next));
    };
    read();
    map.on('moveend', read);
    return () => {
      map.off('moveend', read);
    };
  }, [map, enabled]);
  const rested = useDebouncedValue(bbox, VIEW_REFETCH_DEBOUNCE_MS);
  // The debounced copy lags a reset to null by the delay; never hand out a stale view.
  return bbox && rested ? rested : null;
}

/**
 * Fetches one dashboard widget's aggregate with its layer's saved filter, the
 * reader's picks on the layer's other widgets (`linked`) and, for a
 * view-scoped widget, the map view. A saved filter the endpoint can't take is
 * left out and reported as `filterIgnored`, so the widget can say so.
 */
export function useWidgetAggregate({
  instance,
  definition,
  layer,
  viewBbox,
  embedToken,
  linked = NO_PICKS,
}: {
  instance: WidgetInstance;
  definition: AnyWidgetDefinition;
  layer: SharedLayerResponse;
  viewBbox: Bbox | null;
  embedToken?: string;
  linked?: readonly Cql2Expression[];
}) {
  const { filter, savedIgnored } = useMemo(() => widgetFilter(layer, linked), [layer, linked]);
  // A table has no geometry to bound, so its widgets cover the whole layer.
  const followsView = instance.scope === 'view' && !!layer.geometry_type;
  const body = useMemo(() => {
    const request = definition.dataRequest?.(instance.config);
    if (!request) return null;
    return {
      ...request,
      ...(filter ? { filter } : {}),
      ...(followsView && viewBbox ? { bbox: viewBbox } : {}),
    } as AggregateRequest;
  }, [definition, instance.config, filter, followsView, viewBbox]);

  const query = useQuery({
    queryKey: queryKeys.dashboard.aggregate(layer.dataset_id, layer.tile_version ?? null, body, embedToken ?? ''),
    queryFn: ({ signal }) => fetchAggregate(layer.dataset_id, body!, { embedToken, signal }),
    enabled: body !== null && (!followsView || viewBbox !== null),
    // A pan keeps the last numbers on screen until the new view's arrive.
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    // fetchAggregate paces and retries refused requests itself; a reader retries the rest.
    retry: false,
  });

  return {
    query,
    filterIgnored: savedIgnored,
    // A view-scoped widget is also pending while it waits for the map to rest.
    loading: body !== null && query.isPending,
  };
}
