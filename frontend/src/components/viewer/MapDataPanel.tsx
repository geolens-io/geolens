import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { List, Maximize2, Minimize2, ScanSearch, Table2 } from 'lucide-react';
import { ApiError } from '@/api/client';
import { AttributeTableShell } from '@/components/dataset/AttributeTableShell';
import {
  DockedPanelFrame,
  DockedPanelHeader,
  LayerPicker,
  panelIconButtonClass,
  useRefocusAfterSwitch,
} from '@/components/dataset/DockedPanelFrame';
import { useTableShellSize } from '@/components/dataset/hooks/use-table-shell-size';
import { useMapRowSelection } from '@/components/dataset/hooks/use-map-row-selection';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useIsMobile } from '@/hooks/use-mobile';
import { layerFilterToServerCql2 } from '@/lib/maplibre-filter-utils';
import type { Bbox } from '@/lib/bbox';
import type { SharedLayerResponse } from '@/types/api';
import { AccessibleMapDataPanel } from './AccessibleMapDataPanel';
import type { AccessibleMapFeatureResult } from './accessible-map-data';
import { mapViewBbox, useMapViewBbox } from './hooks/use-dashboard-data';
import type { ViewerLayerEntry } from './layer-identity';
import { combineCql2, inViewFilter, layerHighlightSource, tableColumns } from './map-data-table';

type MapDataView = 'table' | 'list';

const fitPadding = () => 40;
// Below md the docked table keeps three rows under its header; the map shrinks instead.
const PHONE_MIN_HEIGHT = 240;

interface MapDataPanelProps {
  /** The panel's element id, for the launcher's aria-controls. */
  id: string;
  layers: SharedLayerResponse[];
  visibleLayers: Set<string>;
  /** The visible layers readers may open as a table; empty when the map turns the table off. */
  tableEntries: ViewerLayerEntry<SharedLayerResponse>[];
  /** The loaded map. */
  mapRef: React.RefObject<MaplibreMap | null>;
  /** The element the panel and the map share. */
  paneRef: React.RefObject<HTMLElement | null>;
  featureResult: AccessibleMapFeatureResult;
  onRefresh: () => void;
  /** True only when every layer's dataset is public. */
  datasetLinksAllowed: boolean;
  embedToken?: string;
  onClose: () => void;
  /** Told whether the List view shows, the only view that needs the rendered features. */
  onListShownChange: (shown: boolean) => void;
}

function RowsSkeleton({ label }: { label: string }) {
  return (
    <div role="status" className="flex flex-col gap-1.5 p-3">
      <span className="sr-only">{label}</span>
      {Array.from({ length: 5 }, (_, index) => (
        <Skeleton key={index} className="h-5 w-full" />
      ))}
    </div>
  );
}

/** A refused rows request; an expired embed token also gets the viewer's embed toast. */
function TableUnavailable({ error, embedded }: { error: unknown; embedded: boolean }) {
  const { t } = useTranslation('common');
  const expired = embedded && error instanceof ApiError && error.status === 401;
  useEffect(() => {
    if (!expired) return;
    toast.error(t('viewer.embedAuthError', { defaultValue: 'This embedded map\'s access has expired or is no longer valid.' }), {
      id: 'viewer-embed-auth-error',
    });
  }, [expired, t]);
  return <p className="p-4 text-sm text-muted-foreground">{t('viewer.data.unavailable')}</p>;
}

function isRefusal(error: unknown): boolean {
  return error instanceof ApiError && [401, 403, 404].includes(error.status);
}

/**
 * The viewer's Map data panel, docked under the map inside the map pane. Its
 * Table view pages a layer's rows, narrowed by the layer's saved filter, the
 * dashboard picks and optionally the map view; its List view is the text
 * alternative listing what the map renders. On phones an Expand button opens
 * it full screen.
 */
export function MapDataPanel({
  id,
  layers,
  visibleLayers,
  tableEntries,
  mapRef,
  paneRef,
  featureResult,
  onRefresh,
  datasetLinksAllowed,
  embedToken,
  onClose,
  onListShownChange,
}: MapDataPanelProps) {
  const { t } = useTranslation('common');
  const titleId = useId();
  const isPhone = useIsMobile();
  const size = useTableShellSize(mapRef, { ref: paneRef, minHeight: isPhone ? PHONE_MIN_HEIGHT : undefined });

  const tableLayerKeys = useMemo(() => new Set(tableEntries.map(({ key }) => key)), [tableEntries]);
  const [view, setView] = useState<MapDataView>('table');
  const [pickedKey, setPickedKey] = useState<string | null>(null);
  const entry = tableEntries.find(({ key }) => key === pickedKey) ?? tableEntries[0];
  const activeView: MapDataView = view === 'table' && entry ? 'table' : 'list';
  const layer = entry?.layer;
  const layerKey = entry?.key ?? '';
  useEffect(() => onListShownChange(activeView === 'list'), [activeView, onListShownChange]);

  // The first view is read at once, so turning In view on keeps the table
  // mounted; later views arrive once the map rests.
  const [inView, setInView] = useState(false);
  const [firstView, setFirstView] = useState<Bbox | null>(null);
  const restedView = useMapViewBbox(mapRef.current, activeView === 'table' && inView);
  const viewBbox = inView ? restedView ?? firstView : null;
  const toggleInView = (on: boolean) => {
    setInView(on);
    setFirstView(on && mapRef.current ? mapViewBbox(mapRef.current) : null);
  };

  const [expanded, setExpanded] = useState(false);
  const isExpanded = expanded && isPhone;

  const savedCql2 = useMemo(() => (layer ? layerFilterToServerCql2(layer.filter, layer.column_info) : null), [layer]);
  const savedFilter = savedCql2 && savedCql2 !== 'unsupported' ? savedCql2 : null;
  const cql2Filter = useMemo(
    () => combineCql2(savedFilter, viewBbox ? inViewFilter(viewBbox) : null),
    [savedFilter, viewBbox],
  );
  const columns = useMemo(
    () => (layer ? tableColumns(layer, { embedded: !!embedToken, allDatasetsPublic: datasetLinksAllowed }) : undefined),
    [layer, embedToken, datasetLinksAllowed],
  );

  const onOtherLayer = useCallback((key: string) => {
    if (!tableLayerKeys.has(key)) return false;
    setPickedKey(key);
    return true;
  }, [tableLayerKeys]);
  const { selectedGid, highlightFeature } = useMapRowSelection({
    mapRef,
    active: activeView === 'table',
    layerKey,
    getFitPadding: fitPadding,
    onOtherLayer,
  });
  const handleRowClick = (gid: number, bbox?: Bbox | null) => {
    const map = mapRef.current;
    const source = map && entry ? layerHighlightSource(map, entry.layer, entry.key) : null;
    // The map behind a full-screen table can't show the fit.
    setExpanded(false);
    void highlightFeature(gid, bbox && source ? { ...source, bbox } : null);
  };

  const viewRefocus = useRefocusAfterSwitch<HTMLButtonElement>(activeView);
  const pickerRefocus = useRefocusAfterSwitch<HTMLSelectElement>(layerKey);

  const viewSwitch = tableEntries.length > 0 ? (
    <ToggleGroup
      type="single"
      aria-label={t('viewer.data.viewSwitch')}
      value={activeView}
      onValueChange={(value) => {
        if (value !== 'table' && value !== 'list') return;
        viewRefocus.willSwitch();
        setView(value);
      }}
      className="shrink-0 p-0.5"
    >
      {([
        ['table', Table2, t('viewer.data.tableView')],
        ['list', List, t('viewer.data.listView')],
      ] as const).map(([value, Icon, label]) => (
        <ToggleGroupItem
          key={value}
          ref={activeView === value ? viewRefocus.ref : undefined}
          value={value}
          size="sm"
          title={label}
          className="h-6 gap-1 px-1.5 pointer-coarse:min-h-11"
        >
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="max-[399px]:sr-only">{label}</span>
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  ) : null;

  const expandButtonRef = useRef<HTMLButtonElement | null>(null);
  const expandToggle = (inDialog: boolean) => (isPhone ? (
    <button
      ref={inDialog ? undefined : expandButtonRef}
      type="button"
      className={panelIconButtonClass}
      aria-label={inDialog ? t('viewer.data.collapse') : t('viewer.data.expand')}
      title={inDialog ? t('viewer.data.collapse') : t('viewer.data.expand')}
      onClick={() => setExpanded(!inDialog)}
    >
      {inDialog
        ? <Minimize2 className="h-4 w-4" aria-hidden="true" />
        : <Maximize2 className="h-4 w-4" aria-hidden="true" />}
    </button>
  ) : null);

  const headerProps = {
    titleId,
    leading: viewSwitch,
    onClose,
    closeLabel: t('viewer.data.close'),
  };
  const resize = { size, label: t('viewer.data.resize') };
  const rowsLabel = t('viewer.data.loadingRows');

  const renderContent = (inDialog: boolean) => {
    if (activeView === 'list' || !layer) {
      return (
        <DockedPanelFrame resize={inDialog ? undefined : resize}>
          <DockedPanelHeader {...headerProps} title={t('viewer.data.title')} trailing={expandToggle(inDialog)} />
          <AccessibleMapDataPanel
            layers={layers}
            visibleLayers={visibleLayers}
            featureResult={featureResult}
            onRefresh={onRefresh}
            datasetLinksAllowed={datasetLinksAllowed}
            tableLayerKeys={tableLayerKeys}
            onOpenTable={(key) => {
              setPickedKey(key);
              setView('table');
            }}
          />
        </DockedPanelFrame>
      );
    }
    return (
      <AttributeTableShell
        key={layerKey}
        {...headerProps}
        resize={inDialog ? undefined : resize}
        trailing={expandToggle(inDialog)}
        title={layer.display_name || layer.dataset_name}
        picker={tableEntries.length > 1 ? (
          <LayerPicker
            label={t('viewer.data.layerPicker')}
            titleId={titleId}
            options={tableEntries.map(({ layer: option, key }) => ({ id: key, name: option.display_name || option.dataset_name }))}
            value={layerKey}
            onChange={setPickedKey}
            refocus={pickerRefocus}
          />
        ) : undefined}
        extras={(
          <>
            {savedFilter && (
              <span className="whitespace-nowrap rounded-full border px-2 py-0.5 text-xs text-muted-foreground max-md:sr-only">
                {t('viewer.data.filteredByMap')}
              </span>
            )}
            <label className="flex cursor-pointer items-center gap-1.5 whitespace-nowrap text-xs pointer-coarse:min-h-11" title={t('viewer.data.inView')}>
              <Switch checked={inView} onCheckedChange={toggleInView} />
              <ScanSearch className="h-3.5 w-3.5 text-muted-foreground md:hidden" aria-hidden="true" />
              <span className="max-md:sr-only">{t('viewer.data.inView')}</span>
            </label>
          </>
        )}
        notice={savedCql2 === 'unsupported' ? <p role="status">{t('viewer.data.filterUnsupported')}</p> : undefined}
        selectionLabels={{
          missing: t('viewer.data.selectionMissing'),
          show: t('viewer.data.selectionShow'),
          showing: t('viewer.data.selectionShowing'),
          showAll: t('viewer.data.selectionShowAll'),
          hiddenByFilters: t('viewer.data.selectionHiddenByFilters'),
        }}
        table={{
          datasetId: layer.dataset_id,
          compact: true,
          cql2Filter,
          columns,
          rowsRequest: { withBbox: true, embedToken },
          onRowClick: handleRowClick,
          selectedGid,
          slots: {
            empty: inView ? t('viewer.data.emptyInView') : t('viewer.data.emptyFiltered'),
            error: (error) => (isRefusal(error) ? <TableUnavailable error={error} embedded={!!embedToken} /> : undefined),
            loading: <RowsSkeleton label={rowsLabel} />,
          },
          // A docked phone table has room for rows or for per-column filters, not both.
          display: { hideColumnTypes: true, hideColumnFilters: isPhone && !inDialog, announceCount: true },
        }}
      />
    );
  };

  return (
    <>
      <section
        id={id}
        aria-label={t('viewer.data.title')}
        className="flex shrink-0 flex-col overflow-hidden border-t bg-background"
        style={{ height: size.height }}
      >
        {!isExpanded && renderContent(false)}
      </section>
      {isExpanded && (
        <Dialog open onOpenChange={(open) => { if (!open) setExpanded(false); }}>
          <DialogContent
            showCloseButton={false}
            aria-describedby={undefined}
            className="inset-0 top-0 left-0 flex h-dvh w-screen max-w-none translate-x-0 translate-y-0 flex-col gap-0 rounded-none border-0 p-0 sm:max-w-none"
            onCloseAutoFocus={(event) => {
              // The docked panel's Expand button is a new element.
              event.preventDefault();
              expandButtonRef.current?.focus();
            }}
          >
            <DialogTitle className="sr-only">{t('viewer.data.title')}</DialogTitle>
            {renderContent(true)}
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
