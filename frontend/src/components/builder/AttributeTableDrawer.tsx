import { useCallback, useId, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useBuilderLayout } from '@/components/builder/hooks/use-builder-layout';
import { canOpenAttributeTable } from '@/lib/layer-capabilities';
import { Sheet, SheetContent } from '@/components/ui/sheet';
import { AttributeTableShell } from '@/components/dataset/AttributeTableShell';
import { LayerPicker, useRefocusAfterSwitch } from '@/components/dataset/DockedPanelFrame';
import { useTableShellSize } from '@/components/dataset/hooks/use-table-shell-size';
import { useMapRowSelection } from '@/components/dataset/hooks/use-map-row-selection';
import { getFeature } from '@/api/features';
import { layerFilterToServerCql2 } from '@/lib/maplibre-filter-utils';
import type { MapLayerResponse } from '@/types/api';

export interface AttributeTableDrawerProps {
  /** The layer whose dataset the table reads; must satisfy canOpenAttributeTable. */
  layer: MapLayerResponse;
  open: boolean;
  onClose: () => void;
  /** The builder map, for the fit-and-highlight on a row click. */
  mapRef: React.RefObject<MaplibreMap | null>;
  /**
   * The map's layers in map order, for the header's layer picker (options:
   * the ones passing canOpenAttributeTable). Omitted, no picker renders.
   */
  layers?: MapLayerResponse[];
  /** Receives the picker's chosen layer id; omitted, the picker never renders. */
  onLayerChange?: (layerId: string) => void;
}

/**
 * Read-only attribute table for one builder layer, docked under the map at
 * >=800px and a bottom sheet below that. The layer's filter applies to
 * the table via the rows endpoint's CQL2 `filter` param; when the layer filter
 * cannot be converted to CQL2 the table falls back to every row plus a notice,
 * so the table never silently disagrees with the map.
 */
export function AttributeTableDrawer({
  layer,
  open,
  onClose,
  mapRef,
  layers,
  onLayerChange,
}: AttributeTableDrawerProps) {
  const { t } = useTranslation('builder');
  // The layer editor's breakpoint: the table docks at >=800px and uses a
  // bottom sheet below it. Never a separate media-query helper.
  const { isEditorHidden } = useBuilderLayout();
  const isEditorHiddenRef = useRef(isEditorHidden);
  isEditorHiddenRef.current = isEditorHidden;
  const titleId = useId();
  const size = useTableShellSize(mapRef);
  const { height, maxHeight } = size;

  const datasetId = layer.dataset_id;
  const columns = layer.dataset_column_info;

  // null = no filter, 'unsupported' = the rows endpoint can't take it, so the
  // drawer shows the all-rows notice instead.
  const cql2 = useMemo(() => layerFilterToServerCql2(layer.filter, columns), [layer.filter, columns]);
  const filterUnsupported = cql2 === 'unsupported';
  const cql2Filter = cql2 && cql2 !== 'unsupported' ? JSON.stringify(cql2) : undefined;

  const loadFeature = useMemo(
    () => (datasetId ? (gid: number) => getFeature(datasetId, gid) : undefined),
    [datasetId],
  );
  const getFitPadding = useCallback(
    () => (isEditorHiddenRef.current
      ? { top: 40, right: 40, left: 40, bottom: 40 + size.heightRef.current }
      : 40),
    [size.heightRef],
  );
  const { selectedGid, highlightFeature } = useMapRowSelection({
    mapRef,
    active: open,
    layerKey: layer.id,
    loadFeature,
    getFitPadding,
  });

  // Switching layers remounts AttributeTable (key={datasetId}) and the picker with it.
  const pickerRefocus = useRefocusAfterSwitch<HTMLSelectElement>(layer.id);

  const layerName = layer.display_name ?? layer.dataset_name;
  const pickerLayers = layers?.filter(canOpenAttributeTable);

  // The name renders exactly once: with the picker shown it lives only as the
  // picker's selected option, which carries titleId for the frame's
  // aria-labelledby.
  const shell = datasetId && (
    <AttributeTableShell
      key={datasetId}
      title={layerName}
      titleId={titleId}
      picker={pickerLayers && onLayerChange ? (
        <LayerPicker
          label={t('attributeTableDrawer.layerPicker', { defaultValue: 'Attribute table layer' })}
          titleId={titleId}
          options={pickerLayers.map((pickerLayer) => ({
            id: pickerLayer.id,
            name: pickerLayer.display_name ?? pickerLayer.dataset_name,
          }))}
          value={layer.id}
          onChange={onLayerChange}
          refocus={pickerRefocus}
        />
      ) : undefined}
      notice={filterUnsupported ? (
        <p role="status" data-testid="attribute-table-filter-unsupported">
          {t('attributeTableDrawer.filterUnsupported', {
            defaultValue: "The layer's filter could not be applied — showing every row.",
          })}
        </p>
      ) : undefined}
      onClose={onClose}
      closeLabel={t('attributeTableDrawer.close', { defaultValue: 'Close attribute table' })}
      resize={{ size, label: t('attributeTableDrawer.resizeHandle', { defaultValue: 'Resize attribute table' }) }}
      selectionLabels={{
        missing: t('attributeTableDrawer.selectionMissing', { defaultValue: "The selected feature isn't on this page." }),
        show: t('attributeTableDrawer.selectionShow', { defaultValue: 'Show selected' }),
        showing: t('attributeTableDrawer.selectionShowing', { defaultValue: 'Showing the selected feature only.' }),
        showAll: t('attributeTableDrawer.selectionShowAll', { defaultValue: 'Show all rows' }),
        hiddenByFilters: t('attributeTableDrawer.selectionHiddenByFilters', {
          defaultValue: "The selected feature is hidden by the table's filters.",
        }),
      }}
      table={{
        datasetId,
        compact: true,
        cql2Filter,
        onRowClick: (gid) => void highlightFeature(gid),
        selectedGid,
      }}
    />
  );

  // Docked under the map at >=800px: a plain section beside the map, no dialog
  // semantics and no Escape handler — Escape stays with the map; the ✕ closes.
  if (!isEditorHidden) {
    return (
      <section
        aria-labelledby={titleId}
        className="flex flex-col overflow-hidden border-t bg-background shrink-0"
        style={{ height }}
      >
        {shell}
      </section>
    );
  }

  // Below 800px: bounded sheet on the editor's breakpoint; Escape stays
  // with the map, the ✕ closes.
  return (
    <Sheet open={open} modal={false} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent
        side="bottom"
        overlay={false}
        showCloseButton={false}
        onEscapeKeyDown={(event) => event.preventDefault()}
        className="w-full gap-0 overflow-hidden border-t p-0"
        style={{ height, maxHeight }}
        aria-labelledby={titleId}
        aria-describedby={undefined}
      >
        {shell}
      </SheetContent>
    </Sheet>
  );
}
