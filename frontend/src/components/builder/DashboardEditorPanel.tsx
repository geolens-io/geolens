import { memo, Suspense, useCallback, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { arrayMove } from '@dnd-kit/sortable';
import { ArrowDown, ArrowUp, Eye, Plus, Trash2 } from 'lucide-react';
import type { FilterSpecification, Map as MaplibreMap } from 'maplibre-gl';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  DashboardPanel,
  DashboardTextWidget,
  dashboardLayout,
  DashboardWidget,
  widgetName, type PanelPosition,
} from '@/components/viewer/DashboardPanel';
import { useMapViewBbox } from '@/components/viewer/hooks/use-dashboard-data';
import { toSharedLayer } from '@/components/viewer/shared-layer';
import { WIDGET_TITLE_MAX_LENGTH, type AnyWidgetDefinition, type WidgetInstance } from '@/components/widgets/contract';
import { SelectField } from '@/components/widgets/editor-fields';
import { getWidgetDefinition, isLayerBound, widgetDefinitions } from '@/components/widgets/registry';
import { useTheme } from '@/components/theme-provider';
import { useDebouncedValue } from '@/hooks/use-debounce';
import type { Bbox } from '@/lib/bbox';
import { randomId } from '@/lib/random-id';
import { widgetFilterShape } from '@/lib/widget-filter-shape';
import { cn } from '@/lib/utils';
import type { MapLayerResponse } from '@/types/api';
import { LayerFilterEditor } from './LayerFilterEditor';
import {
  dashboardLayers,
  dashboardPayload,
  layerFollowsView,
  MAX_DASHBOARD_WIDGETS,
  widgetProblem,
  type DashboardDraft,
  type DashboardTheme,
  type WidgetProblem,
} from './dashboard-draft';

const DASHBOARD_TYPES = widgetDefinitions.filter((definition) => definition.surfaces.includes('dashboard'));

/** How long a config must rest before its preview asks for data, so typing a number doesn't send one request per key. */
const PREVIEW_DEBOUNCE_MS = 400;

/** A widget's starting config on `layer`: its type's defaults with its picks for the layer's columns. */
function startingConfig(definition: AnyWidgetDefinition, layer?: MapLayerResponse): unknown {
  return {
    ...(definition.defaultConfig as object),
    ...(layer &&
      (definition.initialConfig?.(
        (layer.dataset_column_info ?? []).map((column) => ({
          ...column,
          samples: layer.dataset_sample_values?.[column.name],
        })),
      ) as object | undefined)),
  };
}

function ProblemText({ problem }: { problem: WidgetProblem }) {
  const { t } = useTranslation('widgets');
  return (
    <p className="text-xs text-destructive">
      {problem.kind === 'viewWithoutGeometry' || problem.kind === 'filterUnsupported' || problem.kind === 'filterTooLarge'
        ? t(`editor.problem.${problem.kind}`)
        : problem.kind === 'missingColumn'
          ? t('editor.problem.missingColumn', { column: problem.column })
          : t(`editor.problem.${problem.kind}`, {
              column: problem.column,
            })}
    </p>
  );
}

function LayerScopeFields({
  widget,
  definition,
  idPrefix,
  candidates,
  layer,
  mapHidden,
  onChange,
}: {
  widget: WidgetInstance;
  definition: AnyWidgetDefinition;
  idPrefix: string;
  candidates: readonly MapLayerResponse[];
  layer: MapLayerResponse | undefined;
  mapHidden: boolean;
  onChange: (widget: WidgetInstance) => void;
}) {
  const { t } = useTranslation('widgets');
  // A hidden map has no view to follow.
  const canFollowView = !mapHidden && (layer === undefined || layerFollowsView(layer));
  return (
    <>
      <SelectField
        id={`${idPrefix}-layer`}
        label={t('editor.layer')}
        value={layer ? layer.id : null}
        options={candidates.map((candidate) => ({
          value: candidate.id,
          label: candidate.display_name || candidate.dataset_name,
        }))}
        placeholder={t('editor.pickLayer')}
        // Columns belong to a layer, so another layer starts the config over. A
        // layer without geometry can't follow the map view.
        onChange={(layerId) => {
          const next = candidates.find((candidate) => candidate.id === layerId);
          if (!next) return;
          // The filter names the old layer's columns too.
          const { filter: _filter, ...rest } = widget;
          onChange({
            ...rest,
            layer_id: layerId,
            scope: layerFollowsView(next) ? widget.scope : 'layer',
            config: startingConfig(definition, next),
          });
        }}
      />

      <SelectField
        id={`${idPrefix}-scope`}
        label={t('editor.scope')}
        value={widget.scope ?? 'layer'}
        options={[
          { value: 'layer', label: t('editor.scopeLayer') },
          // Kept while a stored view scope is selected, so the problem below can name it.
          ...(canFollowView || widget.scope === 'view'
            ? [{ value: 'view', label: t('editor.scopeView'), disabled: !canFollowView }]
            : []),
        ]}
        onChange={(scope) => onChange({ ...widget, scope: scope as 'layer' | 'view' })}
      />
      {widget.scope === 'view' && mapHidden && (
        <p className="text-xs text-muted-foreground">{t('dashboard.viewScopeUnavailable')}</p>
      )}
    </>
  );
}

interface WidgetCardProps {
  widget: WidgetInstance;
  definition: AnyWidgetDefinition;
  index: number;
  count: number;
  candidates: readonly MapLayerResponse[];
  /** The widget's layer, when it is still one a widget can summarize. */
  layer: MapLayerResponse | undefined;
  viewBbox: Bbox | null;
  mapHidden: boolean;
  onChange: (widget: WidgetInstance) => void;
  /** Sets the filter of the widget with this id as it is now, since the editor reports it after a delay. */
  onFilterChange: (id: string, filter: FilterSpecification | null) => void;
  onMove: (id: string, by: number) => void;
  onRemove: (id: string) => void;
}

const WidgetCard = memo(function WidgetCard({
  widget,
  definition,
  index,
  count,
  candidates,
  layer,
  viewBbox,
  mapHidden,
  onChange,
  onFilterChange,
  onMove,
  onRemove,
}: WidgetCardProps) {
  const { t } = useTranslation('widgets');
  const idPrefix = useId();
  const typeName = String(t(definition.labelKey));
  const name = widgetName(definition, widget, layer?.dataset_column_info, t) || typeName;
  const layerless = !isLayerBound(definition.type);
  const problem = layer ? widgetProblem(widget, layer) : null;
  const previewConfig = useDebouncedValue(widget.config, PREVIEW_DEBOUNCE_MS);
  const previewFilter = useDebouncedValue(widget.filter, PREVIEW_DEBOUNCE_MS);
  const { filter: _filter, ...unfiltered } = widget;
  const preview = { ...unfiltered, config: previewConfig, ...(previewFilter ? { filter: previewFilter } : {}) };
  // Until the debounce catches up, the preview's config can still name the previous layer's columns.
  const previewReady = layerless || (layer !== undefined && !problem && !widgetProblem(preview, layer));
  // A dataset that limits its tile columns hides the rest from embedded copies, unless anyone can read it in full.
  const tileColumns = layer?.dataset_visibility === 'public' ? null : layer?.dataset_tile_columns;
  const filterColumns = widget.filter ? (widgetFilterShape(widget.filter)?.columns ?? null) : [];
  const hiddenFromEmbeds =
    !!tileColumns &&
    (filterColumns === null ||
      [...(definition.readsColumns?.(widget.config) ?? []).map((use) => use.name), ...filterColumns].some(
        (name) => !tileColumns.includes(name),
      ));
  const Editor = definition.Editor;

  return (
    <li className="space-y-3 rounded-md border p-3">
      <div className="flex items-center gap-1">
        <h3 className="flex-1 truncate text-sm font-medium">{name}</h3>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          disabled={index === 0}
          aria-label={t('editor.moveUp', { name })}
          title={t('editor.moveUp', { name })}
          onClick={() => onMove(widget.id, -1)}
        >
          <ArrowUp aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          disabled={index === count - 1}
          aria-label={t('editor.moveDown', { name })}
          title={t('editor.moveDown', { name })}
          onClick={() => onMove(widget.id, 1)}
        >
          <ArrowDown aria-hidden="true" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label={t('editor.remove', { name })}
          title={t('editor.remove', { name })}
          onClick={() => onRemove(widget.id)}
        >
          <Trash2 aria-hidden="true" />
        </Button>
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs" htmlFor={`${idPrefix}-title`}>
          {t('editor.title')}
        </Label>
        <Input
          id={`${idPrefix}-title`}
          className="h-8"
          maxLength={WIDGET_TITLE_MAX_LENGTH}
          placeholder={typeName}
          value={widget.title ?? ''}
          onChange={(event) => onChange({ ...widget, title: event.target.value })}
        />
      </div>

      {!layerless && (
        <LayerScopeFields
          widget={widget}
          idPrefix={idPrefix}
          candidates={candidates}
          layer={layer}
          definition={definition}
          mapHidden={mapHidden}
          onChange={onChange}
        />
      )}

      {Editor && (layerless || layer) && (
        <Suspense fallback={null}>
          <Editor
            config={widget.config}
            onChange={(config) => onChange({ ...widget, config })}
            columns={layer?.dataset_column_info ?? []}
            idPrefix={idPrefix}
          />
        </Suspense>
      )}

      {layer && definition.filterVersion && (
        <LayerFilterEditor
          // Its conditions name this layer's columns.
          key={layer.id}
          immediate
          columnInfo={(layer.dataset_column_info ?? []).map((column) => ({ name: column.name, type: column.type ?? '' }))}
          filter={widget.filter ?? null}
          onFilterChange={(filter) => onFilterChange(widget.id, filter)}
          title={t('editor.filterTitle')}
          help={t('editor.filterHelp')}
        />
      )}

      {layer && hiddenFromEmbeds && <p className="text-xs text-muted-foreground">{t('editor.embedColumnHint')}</p>}
      {!layerless && !layer && <p className="text-xs text-muted-foreground">{t('editor.problem.layerRemoved')}</p>}
      {problem && <ProblemText problem={problem} />}

      {previewReady && (
        <section aria-label={t('editor.preview')} className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">{t('editor.preview')}</p>
          {layer ? (
            <DashboardWidget
              parsed={{ ok: true, definition, instance: preview }}
              layer={toSharedLayer(layer)}
              viewBbox={widget.scope === 'view' ? viewBbox : null}
              mapHidden={mapHidden}
              headingLevel={4}
            />
          ) : (
            <DashboardTextWidget parsed={{ ok: true, definition, instance: preview }} headingLevel={4} />
          )}
        </section>
      )}
    </li>
  );
});

/**
 * The assembled panel as readers see it, beside a placeholder for the map, at
 * the position the draft chooses. It shows the draft against the Builder's
 * layers, as a save would store it.
 */
function PanelPreview({
  draft,
  layers,
  map,
  open,
  onOpenChange,
}: {
  draft: DashboardDraft;
  layers: readonly MapLayerResponse[];
  map: MaplibreMap | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation('widgets');
  const config = useMemo(() => dashboardPayload(draft, layers, draft), [draft, layers]);
  const layout = dashboardLayout(config);
  const { resolvedTheme } = useTheme();
  // Readers see the selected theme; follow shows the Builder's own.
  const previewTheme = draft.theme === 'light' || draft.theme === 'dark' ? draft.theme : resolvedTheme;
  const shared = useMemo(() => dashboardLayers(layers).map(toSharedLayer), [layers]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{t('editor.previewPanel')}</DialogTitle>
          <DialogDescription>{t('editor.previewPanelDescription')}</DialogDescription>
        </DialogHeader>
        <div
          className={cn(
            'flex h-[70dvh] min-h-0 flex-col overflow-hidden rounded-md border bg-background text-foreground',
            previewTheme,
            layout === 'right' && 'md:flex-row',
          )}
        >
          {layout !== 'page' && (
            <div className="flex min-h-24 flex-1 items-center justify-center bg-muted text-sm text-muted-foreground">
              {t('editor.previewMap')}
            </div>
          )}
          <DashboardPanel config={config} layers={shared} map={map} canZoom={false} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The Builder's dashboard editor: where the panel sits, and the widgets in
 * panel order, each with its type's config editor and a live preview against
 * the Builder's layers and view.
 */
export function DashboardEditorPanel({
  draft,
  onChange,
  layers,
  map,
}: {
  draft: DashboardDraft;
  onChange: (draft: DashboardDraft) => void;
  layers: readonly MapLayerResponse[];
  map: MaplibreMap | null;
}) {
  const { t } = useTranslation('widgets');
  const { t: tCommon } = useTranslation('common');
  const positionId = useId();
  const themeId = useId();
  const [previewing, setPreviewing] = useState(false);
  // Memoized so a title keystroke re-renders only its own card.
  const candidates = useMemo(() => dashboardLayers(layers), [layers]);
  const candidatesById = useMemo(
    () => new Map(candidates.map((candidate) => [candidate.id, candidate])),
    [candidates],
  );
  const mapHidden = !!draft.mapHidden;
  const followsView = !mapHidden && draft.widgets.some((widget) => widget.scope === 'view');
  const viewBbox = useMapViewBbox(map, followsView);

  // The card handlers read the latest draft through a ref, so they keep one
  // identity and an edit to one card leaves the others' props unchanged.
  const latest = useRef({ draft, onChange });
  latest.current = { draft, onChange };
  const setWidgets = useCallback((widgets: (current: WidgetInstance[]) => WidgetInstance[]) => {
    const { draft: current, onChange: change } = latest.current;
    change({ ...current, widgets: widgets(current.widgets) });
  }, []);
  const changeWidget = useCallback(
    (next: WidgetInstance) => setWidgets((widgets) => widgets.map((widget) => (widget.id === next.id ? next : widget))),
    [setWidgets],
  );
  const changeFilter = useCallback(
    (id: string, filter: FilterSpecification | null) =>
      setWidgets((widgets) =>
        widgets.map((widget) => {
          if (widget.id !== id) return widget;
          const { filter: _previous, ...rest } = widget;
          return filter ? { ...rest, filter } : rest;
        }),
      ),
    [setWidgets],
  );
  const moveWidget = useCallback(
    (id: string, by: number) =>
      setWidgets((widgets) => {
        const from = widgets.findIndex((widget) => widget.id === id);
        return arrayMove(widgets, from, from + by);
      }),
    [setWidgets],
  );
  const removeWidget = useCallback(
    (id: string) => setWidgets((widgets) => widgets.filter((widget) => widget.id !== id)),
    [setWidgets],
  );
  const add = (definition: AnyWidgetDefinition) => {
    const layer = isLayerBound(definition.type) ? candidates[0] : undefined;
    setWidgets((widgets) => [
      ...widgets,
      {
        id: randomId(),
        type: definition.type,
        v: definition.v,
        ...(layer && { layer_id: layer.id, scope: 'layer' as const }),
        config: startingConfig(definition, layer),
      },
    ]);
  };
  // The server counts widgets this editor can't see as well, so this is the floor of its limit.
  const full = draft.widgets.length >= MAX_DASHBOARD_WIDGETS;

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-3">
      <SelectField
        id={positionId}
        label={t('editor.panelPosition')}
        value={draft.panel}
        options={[
          { value: 'right', label: t('editor.panelRight') },
          { value: 'bottom', label: t('editor.panelBottom') },
        ]}
        onChange={(panel) => onChange({ ...draft, panel: panel as PanelPosition })}
      />

      <SelectField
        id={themeId}
        label={t('editor.theme')}
        value={draft.theme ?? null}
        placeholder={t('editor.themeFollow')}
        options={[
          { value: 'follow', label: t('editor.themeFollow') },
          { value: 'light', label: tCommon('theme.light') },
          { value: 'dark', label: tCommon('theme.dark') },
        ]}
        onChange={(theme) => onChange({ ...draft, theme: theme as DashboardTheme })}
      />

      {draft.widgets.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('editor.empty')}</p>
      ) : (
        <>
          <div className="flex items-start gap-2">
            <Switch
              id={`${positionId}-hide-map`}
              checked={mapHidden}
              aria-describedby={`${positionId}-hide-map-help`}
              onCheckedChange={(checked) => onChange({ ...draft, mapHidden: checked || undefined })}
            />
            <div className="space-y-0.5">
              <Label className="text-xs" htmlFor={`${positionId}-hide-map`}>
                {t('editor.hideMap')}
              </Label>
              <p id={`${positionId}-hide-map-help`} className="text-xs text-muted-foreground">
                {t('editor.hideMapHelp')}
              </p>
            </div>
          </div>
          <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => setPreviewing(true)}>
            <Eye aria-hidden="true" />
            {t('editor.previewPanel')}
          </Button>
          <ul className="space-y-3">
            {draft.widgets.map((widget, index) => {
              const definition = getWidgetDefinition(widget.type, 'dashboard');
              if (!definition) return null;
              return (
                <WidgetCard
                  key={widget.id}
                  widget={widget}
                  definition={definition}
                  index={index}
                  count={draft.widgets.length}
                  candidates={candidates}
                  layer={candidatesById.get(widget.layer_id ?? '')}
                  viewBbox={widget.scope === 'view' ? viewBbox : null}
                  mapHidden={mapHidden}
                  onChange={changeWidget}
                  onFilterChange={changeFilter}
                  onMove={moveWidget}
                  onRemove={removeWidget}
                />
              );
            })}
          </ul>
        </>
      )}

      {candidates.length === 0 && <p className="text-sm text-muted-foreground">{t('editor.noLayers')}</p>}
      <div className="space-y-2">
        <div className="flex flex-wrap gap-2">
          {DASHBOARD_TYPES.filter((definition) => !isLayerBound(definition.type) || candidates.length > 0).map((definition) => (
            <Button
              key={definition.type}
              type="button"
              variant="outline"
              size="sm"
              disabled={full}
              aria-describedby={full ? `${positionId}-full` : undefined}
              onClick={() => add(definition)}
            >
              <Plus aria-hidden="true" />
              {t('editor.add', { type: t(definition.labelKey) })}
            </Button>
          ))}
        </div>
        {full && (
          <p id={`${positionId}-full`} className="text-xs text-muted-foreground">
            {t('editor.maxWidgets', { max: MAX_DASHBOARD_WIDGETS })}
          </p>
        )}
      </div>

      <PanelPreview draft={draft} layers={layers} map={map} open={previewing} onOpenChange={setPreviewing} />
    </div>
  );
}
