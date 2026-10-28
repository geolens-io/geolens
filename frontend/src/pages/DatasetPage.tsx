import { lazy, Suspense, useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useParams, Link, useNavigate, useLocation } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowLeft, Download, Trash2, Upload, Globe, GlobeLock, Layers, Eye, EyeOff, ShieldAlert, Database, ChevronDown } from 'lucide-react';
import { toast } from 'sonner';
import { PageShell } from '@/components/layout/PageShell';
import { ErrorState } from '@/components/layout/ErrorState';
import { ApiError } from '@/api/client';
import { useDataset, useUpdateDataset, useSetTargetStatus, useValidation, useDatasetRefreshWatch } from '@/components/dataset/hooks/use-dataset';
import { useDatasetJobStatus } from '@/components/import/hooks/use-ingest';
import { IngestWarningsBanner } from '@/components/import/IngestWarningsBanner';
import { useDatasetEditCapabilities, EDITABLE_FIELDS, type DatasetEditField } from '@/components/dataset/hooks/use-dataset-edit-capabilities';
import { useDraftEditing } from '@/components/dataset/hooks/use-draft-editing';
import { useFeatureGid } from '@/components/dataset/hooks/use-feature-gid';
import { useHeroState } from '@/components/dataset/hooks/use-hero-state';
import { useFeatureFlags } from '@/hooks/use-settings';
import { useCanMutate } from '@/hooks/use-can-mutate';
import { usePermissions } from '@/hooks/use-permissions';
import { useAuthStore } from '@/stores/auth-store';
import { useDrawingStore } from '@/stores/drawing-store';
import { DatasetDeleteDialog } from '@/components/dataset/DatasetDeleteDialog';
// Lazy: keeps the dialog and its dropzone/upload deps off the critical path.
const ReuploadDialog = lazy(() =>
  import('@/components/dataset/ReuploadDialog').then((m) => ({ default: m.ReuploadDialog }))
);
// Lazy so the map-vendor chunk is fetched only once the page renders.
const DatasetMap = lazy(() =>
  import('@/components/dataset/DatasetMap').then((m) => ({ default: m.DatasetMap }))
);
import { DatasetDetailSkeleton } from '@/components/dataset/DatasetDetailSkeleton';
import {
  DatasetDetailHeader,
  type DatasetDetailHeaderAction,
} from '@/components/dataset/DatasetDetailHeader';
import { RelatedRecordsPanel } from '@/components/dataset/RelatedRecordsPanel';
// Lazy: DetailPanel imports every dataset-detail tab, so this keeps them off
// the critical path.
const DetailPanel = lazy(() =>
  import('@/components/dataset/panels/DetailPanel').then((m) => ({ default: m.DetailPanel }))
);
import { PendingEditsBar } from '@/components/dataset/PendingEditsBar';
import { ConnectDropdown } from '@/components/dataset/ConnectDropdown';
import { AddToMapButton } from '@/components/dataset/AddToMapButton';
import { DatasetDownloadMenu } from '@/components/dataset/DatasetDownloadMenu';
import { DatasetChatPanel } from '@/components/dataset/DatasetChatPanel';
import { AuthPrompt } from '@/components/auth/AuthPrompt';
const VrtCreateDialog = lazy(() =>
  import('@/components/import/VrtCreateDialog').then((m) => ({ default: m.VrtCreateDialog }))
);
import { RecordTypeBadge } from '@/components/search/RecordTypeBadge';
import { OriginBadge, datasetOrigin } from '@/components/dataset/OriginBadge';
import { FreshnessChip, HealthChip } from '@/components/dataset/SourceStateChips';
import { CopyButton } from '@/components/ui/copy-button';
import { DatasetStatsBar } from '@/components/dataset/DatasetStatsBar';
import { viewablePointCloud, viewableTilesetUrl, type Viewer3DSource } from '@/components/dataset/viewer3d/viewer-support';
import { MapErrorBoundary } from '@/components/error';
import { getValidationNavigationAction } from '@/lib/dataset-validation-navigation';
import { getRecordStatusLabel, getVisibilityLabel } from '@/i18n/labels';
import { Button } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useUnsavedGuard } from '@/hooks/use-unsaved-guard';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { recordTypeCapabilities } from '@/lib/record-types';
import { visibilityColors } from '@/lib/status-colors';
import type { DatasetResponse } from '@/types/api';
import { downloadCog } from '@/api/datasets';

const VALID_TABS = ['overview', 'metadata', 'data', 'structure', 'sources', 'members', 'access'] as const;
const PUBLISH_TARGET = 'published';
const UNPUBLISH_TARGET = 'draft';

function normalizeLegacyTabHash(hash: string): string | null {
  if (hash === 'source-quality' || hash === 'coverage' || hash === 'source-coverage') {
    return 'metadata';
  }
  if (hash === 'access-sharing') return 'access';
  return null;
}

/** Resolve tab hashes, including refresh-run anchors that live in Sources. */
function getTabFromHash(hashValue: string): string | null {
  const hash = hashValue.replace('#', '');
  if (hash.startsWith('refresh-run-')) return 'sources';
  const normalizedLegacyHash = normalizeLegacyTabHash(hash);
  if (normalizedLegacyHash) return normalizedLegacyHash;
  return VALID_TABS.includes(hash as (typeof VALID_TABS)[number]) ? hash : null;
}

/** Initial tab from the URL hash, defaulting to "overview". */
function getInitialTab(): string {
  return getTabFromHash(window.location.hash) ?? 'overview';
}

const FOCUSABLE_SELECTOR = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Scroll the element identified by `anchor` into view and focus it.
 * Retries once via setTimeout(120ms) if the element isn't mounted yet.
 * Returns a cleanup function that cancels any pending retry.
 */
function scrollAndFocus(anchor: string): () => void {
  let timerId: ReturnType<typeof setTimeout> | null = null;

  const focusEl = (el: HTMLElement) => {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const focusable = el.matches(FOCUSABLE_SELECTOR)
      ? el
      : el.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
    focusable?.focus({ preventScroll: true });
  };

  const target = document.querySelector<HTMLElement>(`[data-field-anchor="${anchor}"]`);

  if (!target) {
    timerId = setTimeout(() => {
      const retryTarget = document.querySelector<HTMLElement>(`[data-field-anchor="${anchor}"]`);
      if (retryTarget) focusEl(retryTarget);
    }, 120);
  } else {
    focusEl(target);
  }

  return () => {
    if (timerId) clearTimeout(timerId);
  };
}

function TableHero() {
  const { t } = useTranslation('dataset');
  return (
    <div className="rounded-lg border bg-muted/20 px-4 py-4 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="rounded-lg border bg-background p-2 shadow-sm">
          <Database className="h-5 w-5 text-foreground" />
        </div>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">
              {t('page.dataFirstTitle', { defaultValue: 'Data-first table dataset' })}
            </span>
            <Badge variant="outline" className="text-mini">
              <EyeOff className="me-1 h-3 w-3" />
              {t('page.noMapPreview', { defaultValue: 'No map preview' })}
            </Badge>
          </div>
          <p className="max-w-3xl text-sm text-muted-foreground">
            {t('page.dataFirstDescription', {
              defaultValue: 'This record is a non-spatial table. Review rows below, inspect schema in Structure, and use Connect for downstream access.',
            })}
          </p>
        </div>
      </div>
    </div>
  );
}

export function DatasetPage() {
  const { t } = useTranslation('dataset');
  const { can } = usePermissions();
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: dataset, isLoading, error, refetch } = useDataset(id ?? '', {
    refetchInterval: (query) => {
      const data = (query as { state: { data?: DatasetResponse } }).state.data;
      return data?.raster?.status === 'regenerating' ? 5_000 : false;
    },
  });
  // A missing dataset has no job, validation or refresh runs to ask about.
  const notFound = error instanceof ApiError && error.status === 404;
  const relatedId = notFound ? undefined : id;
  // Page level, not in the Sources tab: that TabsContent unmounts when
  // inactive, and a dispatched refresh's tracking must survive a tab switch.
  const refreshWatch = useDatasetRefreshWatch(relatedId ?? '');
  const [activeDialog, setActiveDialog] = useState<'delete' | 'reupload' | 'vrt' | 'unpublish' | null>(null);
  const setTargetStatus = useSetTargetStatus();
  const token = useAuthStore((s) => s.token);
  const { data: validationData } = useValidation(token ? relatedId : undefined);
  const { data: featureFlags } = useFeatureFlags();
  const [activeTab, setActiveTab] = useState(getInitialTab);
  const navigate = useNavigate();
  const location = useLocation();
  const [pendingNavigationAnchor, setPendingNavigationAnchor] = useState<string | null>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const { effectiveGid, setReadOnlyFeatureGid } = useFeatureGid();

  const [isDataTabExpanded, setIsDataTabExpanded] = useState(false);
  const toggleDataTabExpand = useCallback(() => setIsDataTabExpanded((prev) => !prev), []);
  const [isTaskMapPreviewOpen, setIsTaskMapPreviewOpen] = useState(false);
  // The page stays mounted across a dataset id change (only DetailPanel's key
  // remounts), so per-dataset UI state needs its own reset. A dataset with no
  // Data tab (3D tiles, point cloud) has no control to clear a flag carried
  // over from a table-backed dataset, which would hide the map preview and
  // stats bar for good.
  useEffect(() => {
    setIsTaskMapPreviewOpen(false);
    setIsDataTabExpanded(false);
  }, [id]);
  // Pads the page clear of the fixed AI chat panel, which would otherwise
  // float over the sticky tabs and stat cells.
  const [isChatOpen, setIsChatOpen] = useState(false);
  const isEditor = useAuthStore((s) => s.isEditor());
  // Mirrors the backend check_dataset_write_access: editor capability AND
  // ownership (or admin).
  const canMutate = useCanMutate(dataset);
  const canEdit = isEditor && canMutate;
  // Gives non-owner editors an ownership-specific denied hint instead of the
  // generic viewer copy.
  const notOwnerEditor = isEditor && !canMutate;
  const capabilityHelperOverrides = useMemo<Partial<Record<DatasetEditField, string>> | undefined>(() => {
    if (!notOwnerEditor) return undefined;
    const msg = t('affordances.notOwner', {
      defaultValue: 'Only the dataset owner or an admin can edit this record.',
    });
    return EDITABLE_FIELDS.reduce<Partial<Record<DatasetEditField, string>>>((acc, field) => {
      acc[field] = msg;
      return acc;
    }, {});
  }, [notOwnerEditor, t]);
  const capabilities = useDatasetEditCapabilities(capabilityHelperOverrides, canEdit);
  const isDrawing = useDrawingStore((s) => s.isDrawing);
  const isGeometryEditDirty = useDrawingStore((s) => s.isEditDirty);
  const hasUnsavedMapWork = useDrawingStore((s) => s.hasUnsavedMapWork);
  useDocumentTitle(dataset?.title ?? t('common:pageTitle.dataset'));

  const {
    stagePendingDraft,
    handleDraftDirtyChange,
    resolveDraftValue,
    pendingCount: metadataPendingCount,
    isSaving: isSavingPendingEdits,
    savePendingDrafts,
    discardPendingDrafts,
  } = useDraftEditing({ datasetId: id, dataset, isGeometryEditDirty });

  const {
    isRasterOrVrt,
    tracksHero,
    heroState,
    retryCount,
    mapKey,
    handleRetry,
    handleReplaceComplete,
    onMapReady,
    onTileError,
  } = useHeroState({
    datasetId: id,
    recordType: dataset?.record_type,
    hasTileUrl: !!dataset?.raster?.tile_url,
  });

  // The ingest job carries structured warnings. A 404 is normal: the dataset
  // was registered from an existing table or created via a non-ingest path.
  const { data: datasetJob } = useDatasetJobStatus(relatedId ?? null);

  const handleTabChange = useCallback(
    (value: string) => {
      setActiveTab(value);
      // Router navigation, not a raw `window.location.hash` write, which is a
      // POP the data router did not create and disarms useUnsavedGuard's
      // blocker. `search` is passed because a partial `to` would drop it.
      navigate({ search: location.search, hash: value });
      if (value !== 'data') {
        setIsDataTabExpanded(false);
      }
      setIsTaskMapPreviewOpen(false);
    },
    [navigate, location.search],
  );

  const updateDataset = useUpdateDataset();
  const hasUnsavedChanges = metadataPendingCount > 0 || isGeometryEditDirty || hasUnsavedMapWork;
  const blocker = useUnsavedGuard(hasUnsavedChanges);

  const handleSaveName = useCallback(
    async (newName: string) => {
      if (!id) return;
      await updateDataset.mutateAsync({ datasetId: id, data: { title: newName } });
    },
    [id, updateDataset],
  );

  const handleNavigateToValidationField = useCallback(
    (field: string) => {
      const action = getValidationNavigationAction(field);
      if (!action) return;

      if (action.tab) {
        handleTabChange(action.tab);
      }
      if (action.anchor === 'dataset_map') {
        setIsTaskMapPreviewOpen(true);
      }
      setPendingNavigationAnchor(action.anchor);
    },
    [handleTabChange],
  );

  useEffect(() => {
    const hash = window.location.hash.replace('#', '');
    const normalizedLegacyHash = normalizeLegacyTabHash(hash);
    if (!normalizedLegacyHash) return;

    const nextUrl = `${window.location.pathname}${window.location.search}#${normalizedLegacyHash}`;
    window.history.replaceState(window.history.state, '', nextUrl);
  }, []);

  // Keeps the tab in step with hash changes such as back/forward.
  useEffect(() => {
    const handler = () => {
      const normalized = getTabFromHash(window.location.hash);
      if (normalized) {
        setActiveTab(normalized);
        setIsTaskMapPreviewOpen(false);
      }
    };
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);



  useEffect(() => {
    if (!pendingNavigationAnchor) return;

    let cleanup: (() => void) | null = null;

    const frameId = requestAnimationFrame(() => {
      cleanup = scrollAndFocus(pendingNavigationAnchor);
      setPendingNavigationAnchor(null);
    });

    return () => {
      cancelAnimationFrame(frameId);
      cleanup?.();
    };
  }, [activeTab, pendingNavigationAnchor]);

  if (isLoading) {
    const cached = queryClient.getQueryData<DatasetResponse>(['dataset', id]);
    return <DatasetDetailSkeleton isTable={cached?.record_type === 'table'} />;
  }

  if (error || !dataset) {
    return (
      <PageShell>
        <ErrorState
          title={t('page.errorTitle')}
          message={error instanceof Error ? error.message : t('page.errorMessage')}
          onRetry={notFound ? undefined : () => refetch()}
          action={
            <Link
              to="/"
              className="text-sm text-primary hover:underline inline-flex items-center gap-1 transition-colors duration-150"
            >
              <ArrowLeft className="h-4 w-4 rtl-mirror" />
              {t('page.backToSearch')}
            </Link>
          }
        />
      </PageShell>
    );
  }

  const bbox =
    dataset.extent_bbox && dataset.extent_bbox.length >= 4
      ? (dataset.extent_bbox as [number, number, number, number])
      : null;

  const isRaster = dataset.record_type === 'raster_dataset';
  const isVrt = dataset.record_type === 'vrt_dataset';
  const isTable = dataset.record_type === 'table';
  const isTileset = dataset.record_type === 'tiles3d_dataset';
  const isPointCloud = dataset.record_type === 'pointcloud_dataset';
  // Neither type has in-app tiles, so the preview shows only the extent as an
  // outline over the basemap.
  const tilesetUrl = isTileset ? viewableTilesetUrl(dataset.tileset) : null;
  const viewer3d: Viewer3DSource | null = tilesetUrl
    ? { kind: 'tileset', url: tilesetUrl }
    : isPointCloud && bbox !== null
      ? viewablePointCloud(dataset.pointcloud)
      : null;
  const showFootprintOnly = (isTileset || isPointCloud) && bbox !== null;
  const { featureTable, mapLayerType, tileToken: tileKind } = recordTypeCapabilities(dataset.record_type);
  const canAddToMap = !isTable && mapLayerType !== null;
  const canReupload = featureTable || isRaster;
  // DetailPanel deep-links Data/Structure to Overview for record types without
  // those tabs. The page-level map must use the same effective tab, or an
  // activeTab left over from a table-backed dataset would render this one's
  // footprint in the collapsed task-tab state.
  const effectivePageTab = (isRaster || isVrt || isTileset || isPointCloud)
    && (activeTab === 'data' || activeTab === 'structure')
    ? 'overview'
    : activeTab;
  const isOverview = effectivePageTab === 'overview';
  const isMapPreviewOpen = isOverview || isDrawing || isTaskMapPreviewOpen;

  const isPublished = dataset.record_status === 'published';
  const hasValidationErrors = validationData ? validationData.errors.length > 0 : false;
  const requireMetadata = featureFlags?.require_metadata_for_publish ?? false;
  const dataEditingEnabled = featureFlags?.enable_dataset_editing ?? false;

  // The flag gates geometry drawing and cell editing; metadata editing and
  // management actions stay ungated.
  const canEditData = canEdit && dataEditingEnabled;

  // A 422 carries the workflow's own refusal, already localized by the API client.
  const publishFailureMessage = (err: unknown) =>
    err instanceof ApiError && err.status === 422
      ? err.message
      : t('publish.failed');

  const handlePublishToggle = async () => {
    if (!id) return;
    if (isPublished) {
      setActiveDialog('unpublish');
      return;
    }
    if (requireMetadata && hasValidationErrors) {
      toast.error(t('publish.validationBlocker', { defaultValue: 'Resolve validation issues before publishing' }));
      return;
    }
    try {
      const result = await setTargetStatus.mutateAsync({ datasetId: id, status: PUBLISH_TARGET });
      toast.success(t('publish.success'));
      // Publishing goes through target-status, not the metadata PATCH, so the
      // inherited-keyword warning comes from this response.
      if (result.metadata_warnings?.length) {
        toast.warning(result.metadata_warnings[0]);
      }
    } catch (err) {
      toast.error(publishFailureMessage(err));
    }
  };

  const handleUnpublish = async () => {
    if (!id) return;
    try {
      await setTargetStatus.mutateAsync({ datasetId: id, status: UNPUBLISH_TARGET });
      toast.success(t('publish.unpublished'));
    } catch (err) {
      toast.error(publishFailureMessage(err));
    } finally {
      setActiveDialog(null);
    }
  };

  // record_status (catalog publish state) and visibility (access control) are
  // orthogonal: a dataset can be published yet private, e.g. right after
  // upload. The header labels both axes so "Unpublish" never sits beside only a
  // "Private" badge.
  const origin = datasetOrigin(dataset);
  // The table name in the header lets psql, QGIS and ogr2ogr hit the data
  // directly. Raster/VRT data lives in object storage, so it skips the readout.
  const showTableReadout = featureTable && Boolean(dataset.table_name);

  const statsLine = (
    <>
      <RecordTypeBadge recordType={dataset.record_type} />
      <div className="flex flex-wrap items-center gap-1.5">
        {origin && <OriginBadge origin={origin} />}
        <FreshnessChip state={dataset.source_freshness} />
        <HealthChip state={dataset.source_health} />
        <Badge variant="outline" className={cn('text-xs', visibilityColors[dataset.visibility] ?? '')}>
          {dataset.visibility === 'public' ? <Eye className="me-1 h-3 w-3" /> : dataset.visibility === 'restricted' ? <ShieldAlert className="me-1 h-3 w-3" /> : <EyeOff className="me-1 h-3 w-3" />}
          {t('header.catalogStatus', {
            status: getRecordStatusLabel(t, dataset.record_status),
            visibility: getVisibilityLabel(t, dataset.visibility),
            defaultValue: 'Catalog: {{status}} · {{visibility}}',
          })}
        </Badge>
      </div>
      {showTableReadout && (
        <span
          className="inline-flex min-w-0 max-w-full items-center gap-0.5 readout text-xs text-muted-foreground"
          title={t('header.tableReadout', { defaultValue: 'PostGIS table' })}
          data-testid="dataset-table-readout"
        >
          <span className="min-w-0 truncate" title={dataset.table_name}>{dataset.table_name}</span>
          <CopyButton value={dataset.table_name} className="inline-flex size-5 shrink-0 items-center justify-center rounded-sm hover:bg-muted transition-colors pointer-coarse:-m-3 pointer-coarse:size-11" />
        </span>
      )}
    </>
  );

  const headerActions: DatasetDetailHeaderAction[] = [
    {
      id: 'publish',
      label: isPublished ? t('publish.unpublish') : t('publish.publish'),
      icon: isPublished ? GlobeLock : Globe,
      onSelect: handlePublishToggle,
      priority: 5,
      visible: canEdit,
      disabled: setTargetStatus.isPending,
    },
    {
      id: 'reupload',
      label: t('actions.reupload'),
      tooltip: t('actions.reuploadTooltip', { defaultValue: "Replace this dataset's source file" }),
      icon: Upload,
      onSelect: () => setActiveDialog('reupload'),
      priority: 10,
      // Raster reupload skips the vector schema-preview step. VRT is excluded;
      // it keeps the regenerate action.
      visible: canEdit && canReupload,
      variant: 'outline',
    },
    {
      id: 'create-vrt',
      label: t('actions.createVrt', { defaultValue: 'Create VRT' }),
      tooltip: t('actions.createVrtTooltip', { defaultValue: 'Create a VRT mosaic from this raster' }),
      icon: Layers,
      onSelect: () => setActiveDialog('vrt'),
      priority: 11,
      // Creates a NEW dataset without mutating the source, so it needs
      // read + upload capability (isEditor), not source ownership. The backend
      // authorizes the source via check_dataset_access.
      visible: isRaster && isEditor,
    },
    {
      id: 'delete',
      label: t('actions.delete'),
      tooltip: t('actions.deleteTooltip', { defaultValue: 'Delete this dataset' }),
      icon: Trash2,
      onSelect: () => setActiveDialog('delete'),
      priority: 20,
      visible: canEdit,
      variant: 'destructive',
    },
  ];

  return (
    <PageShell className={cn('transition-[padding] duration-200', isChatOpen && 'lg:pe-[26.5rem]')}>
      <DatasetDetailHeader
        title={dataset.title}
        onTitleSave={handleSaveName}
        canEditTitle={canEdit}
        breadcrumbs={[{ label: t('breadcrumbs.datasets'), to: '/' }]}
        actions={headerActions}
        statsLine={statsLine}
        leadingContent={
          <div className="flex flex-wrap items-center gap-2 @5xl:flex-nowrap">
            {canAddToMap && can('edit_metadata') && <AddToMapButton datasetId={dataset.id} datasetTitle={dataset.title} />}
            {!token && (canAddToMap || isTable) && (
              <AuthPrompt
                action={
                  canAddToMap
                    ? t('actions.addToMap', { defaultValue: 'add to a map' })
                    : t('actions.edit', { defaultValue: 'edit' })
                }
              />
            )}
            {isRaster && dataset.raster?.connect && (
              <Button variant="outline" size="sm" onClick={async () => {
                try { await downloadCog(dataset.id); } catch { toast.error(t('export.failed')); }
              }}>
                <Download className="me-1 size-3" />
                {t('actions.downloadCog', { defaultValue: 'Download COG' })}
              </Button>
            )}
            {featureTable && (
              <DatasetDownloadMenu datasetId={dataset.id} datasetName={dataset.title} geometryType={dataset.geometry_type} />
            )}
            <ConnectDropdown dataset={dataset} onShowInstructions={() => handleTabChange('access')} />
          </div>
        }
      />

      {/* Failed re-import warnings may not describe the live dataset. */}
      {datasetJob?.status === 'complete' && (
        <IngestWarningsBanner key={datasetJob.id} job={datasetJob} compact className="mb-3" />
      )}

      {/* Hero Data Grid for table datasets (no map) */}
      {isTable && <TableHero />}

      {/* Task tabs lead with their own work instead of a full-height map. A
          3D Tiles tileset or COPC file the viewer can draw renders in it; other
          3D datasets get a map section only to show an existing extent. Expanding the Data tab would unmount this
          section and destroy an in-progress geometry edit, which lives only in
          this map's TerraDraw instance; toggling isDataTabExpanded doesn't
          change the route, so the unsaved-changes guard never sees it. The
          section stays mounted, just hidden, while a session is active. */}
      {(!isDataTabExpanded || isDrawing) && !isTable && (!(isTileset || isPointCloud) || showFootprintOnly || viewer3d !== null) && (
        <section
          aria-label={t('page.mapPreview')}
          className={cn('rounded-lg border shadow-sm overflow-hidden', isDataTabExpanded && 'hidden')}
        >
          {!isOverview && !isDrawing && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="w-full justify-between rounded-none px-3"
              aria-expanded={isMapPreviewOpen}
              aria-controls="dataset-map-preview"
              onClick={() => setIsTaskMapPreviewOpen((open) => !open)}
            >
              <span>{t(isMapPreviewOpen ? 'page.hideMapPreview' : 'page.showMapPreview')}</span>
              <ChevronDown className={cn('size-4 transition-transform', isMapPreviewOpen && 'rotate-180')} />
            </Button>
          )}
          <div
            id="dataset-map-preview"
            ref={mapContainerRef}
            data-field-anchor="dataset_map"
            tabIndex={-1}
            className={cn(
              'relative overflow-hidden transition-[height] duration-300 ease-in-out',
              !isMapPreviewOpen && 'hidden',
              isDrawing ? 'h-[60vh]' : isOverview ? 'h-72 lg:h-96' : 'h-52 lg:h-56',
            )}
          >
            {tracksHero && heroState === 'loading' && (
              <Skeleton data-testid="hero-skeleton" className="absolute inset-0 z-10 rounded-lg" />
            )}
            <MapErrorBoundary>
              <Suspense
                fallback={
                  <Skeleton
                    data-testid="dataset-map-suspense"
                    className="absolute inset-0 z-10 rounded-lg"
                  />
                }
              >
                {/* geometryType stays the concrete display type;
                    hasGenericGeometry separately gates the drawing toolbar so
                    generic sketch layers keep every draw mode. */}
                <DatasetMap
                  // A map keeps every source it was given, so each dataset needs
                  // its own instance (for raster/VRT also per tile kind, DEM or
                  // imagery source type, and DEM extent).
                  key={`${dataset.id}:${isRasterOrVrt ? `${mapKey}:${dataset.raster?.is_dem ? `dem:${bbox?.join(',')}` : 'img'}` : tileKind ?? 'no-tiles'}`}
                  bbox={bbox}
                  tableName={dataset.table_name}
                  geometryType={dataset.geometry_type ?? null}
                  hasGenericGeometry={dataset.has_generic_geometry}
                  datasetId={id}
                  columnInfo={dataset.column_info}
                  containerRef={mapContainerRef}
                  canEdit={canEditData && featureTable && !isTable}
                  recordType={dataset.record_type}
                  viewer3d={viewer3d}
                  rasterTileUrl={dataset.raster?.tile_url}
                  isDem={dataset.raster?.is_dem ?? false}
                  tileVersion={dataset.updated_at}
                  attribution={dataset.attribution}
                  shortcutsEnabled={!isDataTabExpanded}
                  onFeatureClick={setReadOnlyFeatureGid}
                  {...(tracksHero ? {
                    onMapReady,
                    onTileError,
                  } : {})}
                />
              </Suspense>
            </MapErrorBoundary>
            {dataset.record_type === 'raster_dataset' && !dataset.raster?.tile_url && heroState === 'loaded' && (
              <div className="absolute bottom-2 start-2 z-10 px-2 py-1 rounded-sm bg-muted/80 text-xs text-muted-foreground">
                {t('raster.noTiles')}
              </div>
            )}
            {tracksHero && heroState === 'error' && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-background/80 rounded-lg z-10">
                <AlertTriangle className="size-8 text-destructive mb-2" />
                <p className="text-sm text-muted-foreground mb-3">{t('raster.previewUnavailable')}</p>
                {retryCount < 3 ? (
                  <Button size="sm" onClick={handleRetry}>{t('raster.retry')}</Button>
                ) : (
                  <p className="text-xs text-muted-foreground">{t('raster.tilesProcessing')}</p>
                )}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Stats instrument bar — key metrics at a glance */}
      {!isDataTabExpanded && (
        <DatasetStatsBar dataset={dataset} className="-mx-px" />
      )}

      {/* Tabbed content — tabs shown are driven by record_type */}
      <Suspense fallback={<DatasetDetailSkeleton isTable={isTable} />}>
        {/* The page stays mounted across a dataset-to-dataset route change, so
            InlineEdit drafts would carry over and a save could PATCH dataset A's
            keystrokes onto B. Keying on the dataset id remounts the subtree and
            resets them. useDraftEditing's own datasetId-keyed reset covers the
            already-staged case. */}
        <DetailPanel
          key={dataset.id}
          dataset={dataset}
          canEdit={canEdit}
          canEditData={canEditData}
          canManageKeys={canMutate}
          capabilities={capabilities}
          activeTab={activeTab}
          onTabChange={handleTabChange}
          resolveDraftValue={resolveDraftValue}
          stagePendingDraft={stagePendingDraft}
          handleDraftDirtyChange={handleDraftDirtyChange}
          onNavigateToValidationField={handleNavigateToValidationField}
          isTableExpanded={isDataTabExpanded}
          onToggleTableExpand={toggleDataTabExpand}
          refreshWatch={refreshWatch}
        />
      </Suspense>

      {/* Related records panel -- shown when a feature is selected (editing or read-only) */}
      {effectiveGid != null && (dataset.record_type === 'vector_dataset' || dataset.record_type === 'table' || !dataset.record_type) && (
        <RelatedRecordsPanel datasetId={id!} featureGid={effectiveGid} />
      )}

      <PendingEditsBar
        pendingCount={metadataPendingCount}
        onSaveAll={async () => { await savePendingDrafts(); }}
        onCancelAll={discardPendingDrafts}
        isSaving={isSavingPendingEdits}
      />

      {/* Dataset-scoped AI chat: vector/table datasets only, like the backend
          record_type gate. The panel also self-gates on AI availability +
          use_ai_chat, so anonymous visitors see nothing. */}
      {token && featureTable && (
        <DatasetChatPanel
          datasetId={dataset.id}
          datasetTitle={dataset.title}
          showOpenInBuilder={!isTable}
          onOpenChange={setIsChatOpen}
          abovePendingBar={metadataPendingCount > 0}
        />
      )}

      {/* Dialogs */}
      {canEdit && (
        <DatasetDeleteDialog
          dataset={dataset}
          open={activeDialog === 'delete'}
          onOpenChange={(open) => setActiveDialog(open ? 'delete' : null)}
        />
      )}

      {canEdit && canReupload && (
        <Suspense fallback={null}>
          <ReuploadDialog
            dataset={dataset}
            open={activeDialog === 'reupload'}
            onOpenChange={(open) => setActiveDialog(open ? 'reupload' : null)}
            // A raster's tile URL is fixed per dataset and the hero map adds
            // its source once, so a completed replacement needs an explicit
            // remount. handleReplaceComplete, not handleRetry, which would
            // spend the 3-attempt manual-retry budget on every success.
            onReplaceComplete={handleReplaceComplete}
          />
        </Suspense>
      )}

      {isRaster && isEditor && (
        <Suspense fallback={null}>
          <VrtCreateDialog
            open={activeDialog === 'vrt'}
            onOpenChange={(open) => setActiveDialog(open ? 'vrt' : null)}
            initialSourceId={dataset.id}
          />
        </Suspense>
      )}

      <AlertDialog open={activeDialog === 'unpublish'} onOpenChange={(open) => setActiveDialog(open ? 'unpublish' : null)}>
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('publish.unpublishTitle', { defaultValue: 'Unpublish Dataset?' })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('publish.confirmUnpublish')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel', { defaultValue: 'Cancel' })}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={handleUnpublish}>
              {t('publish.unpublish')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={blocker.state === 'blocked'} onOpenChange={() => blocker.reset?.()}>
        <AlertDialogContent size="sm">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('unsaved.title', { defaultValue: 'Unsaved Changes' })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('unsaved.description', { defaultValue: 'You have unsaved changes. Are you sure you want to leave? Your changes will be lost.' })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => blocker.reset?.()}>
              {t('unsaved.stay', { defaultValue: 'Stay' })}
            </AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                // Leaving must discard, or the staged drafts reappear (and
                // could PATCH) on whatever mounts next.
                discardPendingDrafts();
                blocker.proceed?.();
              }}
            >
              {t('unsaved.leave', { defaultValue: 'Leave' })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}
