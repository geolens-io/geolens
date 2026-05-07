import { lazy, Suspense, useState, useCallback, useEffect, useRef } from 'react';
import { useParams, Link } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowLeft, Download, Trash2, Upload, Globe, GlobeLock, Layers, Eye, EyeOff, ShieldAlert, Database } from 'lucide-react';
import { toast } from 'sonner';
import { PageShell } from '@/components/layout/PageShell';
import { ErrorState } from '@/components/layout/ErrorState';
import { useDataset, useUpdateDataset, useSetTargetStatus, useValidation } from '@/components/dataset/hooks/use-dataset';
import { useDatasetJobStatus } from '@/components/import/hooks/use-ingest';
import { IngestWarningsBanner } from '@/components/import/IngestWarningsBanner';
import { useDatasetEditCapabilities } from '@/components/dataset/hooks/use-dataset-edit-capabilities';
import { useDraftEditing } from '@/components/dataset/hooks/use-draft-editing';
import { useFeatureGid } from '@/components/dataset/hooks/use-feature-gid';
import { useHeroState } from '@/components/dataset/hooks/use-hero-state';
import { useFeatureFlags } from '@/hooks/use-settings';
import { useAuthStore } from '@/stores/auth-store';
import { useDrawingStore } from '@/stores/drawing-store';
import { DatasetDeleteDialog } from '@/components/dataset/DatasetDeleteDialog';
// Phase 276 CODE-06: lazy-load ReuploadDialog — only fetched when the
// user opens the reupload flow (activeDialog === 'reupload'). Splits the
// dialog and its dropzone/upload deps off the page-mount critical path.
const ReuploadDialog = lazy(() =>
  import('@/components/dataset/ReuploadDialog').then((m) => ({ default: m.ReuploadDialog }))
);
// PERF-06 (Phase 274): lazy-load DatasetMap so map-vendor chunk is fetched
// only when this page actually renders (after data fetch resolves).
const DatasetMap = lazy(() =>
  import('@/components/dataset/DatasetMap').then((m) => ({ default: m.DatasetMap }))
);
import { DatasetDetailSkeleton } from '@/components/dataset/DatasetDetailSkeleton';
import {
  DatasetDetailHeader,
  type DatasetDetailHeaderAction,
} from '@/components/dataset/DatasetDetailHeader';
import { RelatedRecordsPanel } from '@/components/dataset/RelatedRecordsPanel';
// Phase 276 CODE-06: lazy-load DetailPanel — DetailPanel transitively
// imports all six dataset-detail tabs (Overview/Metadata/Data/Structure/Sources/Access).
// Lazifying it splits the per-tab code paths off the page-mount critical path;
// the active-tab content streams in via Suspense after first paint.
const DetailPanel = lazy(() =>
  import('@/components/dataset/panels/DetailPanel').then((m) => ({ default: m.DetailPanel }))
);
import { PendingEditsBar } from '@/components/dataset/PendingEditsBar';
import { ConnectDropdown } from '@/components/dataset/ConnectDropdown';
import { AddToMapButton } from '@/components/dataset/AddToMapButton';
import { AuthPrompt } from '@/components/auth/AuthPrompt';
// Phase 276 CODE-06: lazy-load VrtCreateDialog — only fetched when the
// user opens the VRT creation flow (activeDialog === 'vrt').
const VrtCreateDialog = lazy(() =>
  import('@/components/import/VrtCreateDialog').then((m) => ({ default: m.VrtCreateDialog }))
);
import { RecordTypeBadge } from '@/components/search/RecordTypeBadge';
import { DatasetStatsBar } from '@/components/dataset/DatasetStatsBar';
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

/** Read initial tab from URL hash, defaulting to "overview" */
function getInitialTab(): string {
  const hash = window.location.hash.replace('#', '');
  const normalizedLegacyHash = normalizeLegacyTabHash(hash);
  if (normalizedLegacyHash) return normalizedLegacyHash;
  return VALID_TABS.includes(hash as (typeof VALID_TABS)[number]) ? hash : 'overview';
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
            <Badge variant="outline" className="text-[11px]">
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
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: dataset, isLoading, error } = useDataset(id ?? '', {
    refetchInterval: (query) => {
      const data = (query as { state: { data?: DatasetResponse } }).state.data;
      return data?.raster?.status === 'regenerating' ? 5_000 : false;
    },
  });
  const [activeDialog, setActiveDialog] = useState<'delete' | 'reupload' | 'vrt' | 'unpublish' | null>(null);
  const setTargetStatus = useSetTargetStatus();
  const token = useAuthStore((s) => s.token);
  const { data: validationData } = useValidation(token ? id : undefined);
  const { data: featureFlags } = useFeatureFlags();
  const [activeTab, setActiveTab] = useState(getInitialTab);
  const [pendingNavigationAnchor, setPendingNavigationAnchor] = useState<string | null>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const { effectiveGid, setReadOnlyFeatureGid } = useFeatureGid();

  const [isDataTabExpanded, setIsDataTabExpanded] = useState(false);
  const toggleDataTabExpand = useCallback(() => setIsDataTabExpanded((prev) => !prev), []);
  const isAdmin = useAuthStore((s) => s.isAdmin());
  const isEditor = useAuthStore((s) => s.isEditor());
  const capabilities = useDatasetEditCapabilities();
  const isDrawing = useDrawingStore((s) => s.isDrawing);
  const isGeometryEditDirty = useDrawingStore((s) => s.isEditDirty);
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
    heroState,
    retryCount,
    mapKey,
    handleRetry,
    onMapReady,
    onTileError,
  } = useHeroState({
    datasetId: id,
    recordType: dataset?.record_type,
    hasTileUrl: !!dataset?.raster?.tile_url,
  });

  // S3: fetch the ingest job for this dataset to surface structured warnings
  // (reserved_rename, dbf_truncation_collision, archive_failed, temporal_parse_errors).
  // 404 is a normal case — the dataset was registered from an existing table
  // or created via a non-ingest path.
  const { data: datasetJob } = useDatasetJobStatus(id ?? null);

  const handleTabChange = useCallback((value: string) => {
    setActiveTab(value);
    window.location.hash = value;
    if (value !== 'data') {
      setIsDataTabExpanded(false);
    }
  }, []);

  const updateDataset = useUpdateDataset();
  const hasUnsavedChanges = metadataPendingCount > 0 || isGeometryEditDirty;
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

  // Sync active tab when hash changes (e.g. browser back/forward)
  useEffect(() => {
    const handler = () => {
      const hash = window.location.hash.replace('#', '');
      const normalized = normalizeLegacyTabHash(hash) ?? hash;
      if (VALID_TABS.includes(normalized as (typeof VALID_TABS)[number])) {
        setActiveTab(normalized);
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

  const isPublished = dataset.record_status === 'published';
  const hasValidationErrors = validationData ? validationData.errors.length > 0 : false;
  const requireMetadata = featureFlags?.require_metadata_for_publish ?? false;
  const dataEditingEnabled = featureFlags?.enable_dataset_editing ?? false;

  // Gate geometry drawing and attribute cell editing behind the feature flag.
  // Metadata editing (overview/metadata tabs) and management actions remain ungated.
  const canEditData = isEditor && dataEditingEnabled;

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
      await setTargetStatus.mutateAsync({ datasetId: id, status: PUBLISH_TARGET });
      toast.success(t('publish.success'));
    } catch {
      toast.error(t('publish.failed'));
    }
  };

  const handleUnpublish = async () => {
    if (!id) return;
    try {
      await setTargetStatus.mutateAsync({ datasetId: id, status: UNPUBLISH_TARGET });
      toast.success(t('publish.unpublished'));
    } catch {
      toast.error(t('publish.failed'));
    } finally {
      setActiveDialog(null);
    }
  };

  const statsLine = (
    <>
      <RecordTypeBadge recordType={dataset.record_type} />
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span>{getRecordStatusLabel(t, dataset.record_status)}</span>
        <span className="text-muted-foreground/50">·</span>
        <Badge variant="outline" className={cn('text-xs', visibilityColors[dataset.visibility] ?? '')}>
          {dataset.visibility === 'public' ? <Eye className="me-1 h-3 w-3" /> : dataset.visibility === 'restricted' ? <ShieldAlert className="me-1 h-3 w-3" /> : <EyeOff className="me-1 h-3 w-3" />}
          {getVisibilityLabel(t, dataset.visibility)}
        </Badge>
      </div>
    </>
  );

  const headerActions: DatasetDetailHeaderAction[] = [
    {
      id: 'publish',
      label: isPublished ? t('publish.unpublish') : t('publish.publish'),
      icon: isPublished ? GlobeLock : Globe,
      onSelect: handlePublishToggle,
      priority: 5,
      visible: isEditor,
      disabled: setTargetStatus.isPending,
    },
    {
      id: 'reupload',
      label: t('actions.reupload'),
      icon: Upload,
      onSelect: () => setActiveDialog('reupload'),
      priority: 10,
      visible: isEditor && !isVrt,
      variant: 'outline',
    },
    {
      id: 'create-vrt',
      label: t('actions.createVrt', { defaultValue: 'Create VRT' }),
      icon: Layers,
      onSelect: () => setActiveDialog('vrt'),
      priority: 11,
      visible: isRaster && isEditor,
    },
    {
      id: 'delete',
      label: t('actions.delete'),
      icon: Trash2,
      onSelect: () => setActiveDialog('delete'),
      priority: 20,
      visible: isAdmin,
      variant: 'destructive',
    },
  ];

  return (
    <PageShell>
      <DatasetDetailHeader
        title={dataset.title}
        onTitleSave={handleSaveName}
        canEditTitle={isEditor}
        breadcrumbs={[{ label: t('breadcrumbs.datasets'), to: '/' }]}
        actions={headerActions}
        statsLine={statsLine}
        leadingContent={
          <div className="flex items-center gap-2">
            {!isTable && isEditor && <AddToMapButton datasetId={dataset.id} datasetTitle={dataset.title} />}
            {!token && <AuthPrompt action={t('actions.edit', { defaultValue: 'edit' })} />}
            {isRaster && dataset.raster?.connect && (
              <Button variant="default" size="sm" onClick={() => {
                try { downloadCog(dataset.id); } catch { toast.error(t('export.failed')); }
              }}>
                <Download className="me-1 size-3" />
                {t('actions.downloadCog', { defaultValue: 'Download COG' })}
              </Button>
            )}
            <ConnectDropdown dataset={dataset} />
          </div>
        }
      />

      {/* S3: persistent ingest warnings (reserved renames, DBF collisions,
          archive failures, temporal parse errors). Rendered permanently for
          successfully-completed jobs only — a failed re-import may have
          partially-recorded warnings that don't apply to the live dataset. */}
      {datasetJob?.status === 'complete' && (
        <IngestWarningsBanner job={datasetJob} className="mb-3" />
      )}

      {/* Hero Data Grid for table datasets (no map) */}
      {isTable && <TableHero />}

      {/* Hero Map -- visible for all spatial dataset types */}
      {!isDataTabExpanded && !isTable && (
        <div
          ref={mapContainerRef}
          data-field-anchor="dataset_map"
          tabIndex={-1}
          className={cn(
            'rounded-lg border shadow-sm overflow-hidden relative transition-[height] duration-300 ease-in-out',
            isDrawing ? 'h-[60vh]' : 'h-72 lg:h-96'
          )}
        >
          {isRasterOrVrt && heroState === 'loading' && (
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
              <DatasetMap
                key={isRasterOrVrt ? mapKey : undefined}
                bbox={bbox}
                tableName={dataset.table_name}
                geometryType={dataset.geometry_type}
                datasetId={id}
                columnInfo={dataset.column_info}
                containerRef={mapContainerRef}
                canEdit={canEditData && !isRaster && !isVrt && !isTable}
                recordType={dataset.record_type}
                rasterTileUrl={dataset.raster?.tile_url}
                tileVersion={dataset.updated_at}
                onFeatureClick={setReadOnlyFeatureGid}
                {...(isRasterOrVrt ? {
                  onMapReady,
                  onTileError,
                } : {})}
              />
            </Suspense>
          </MapErrorBoundary>
          {dataset.record_type === 'raster_dataset' && !dataset.raster?.tile_url && heroState === 'loaded' && (
            <div className="absolute bottom-2 left-2 z-10 px-2 py-1 rounded bg-muted/80 text-xs text-muted-foreground">
              {t('raster.noTiles')}
            </div>
          )}
          {isRasterOrVrt && heroState === 'error' && (
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
      )}

      {/* Stats instrument bar — key metrics at a glance */}
      {!isDataTabExpanded && (
        <DatasetStatsBar dataset={dataset} className="-mx-px" />
      )}

      {/* Tabbed content — tabs shown are driven by record_type */}
      <Suspense fallback={<DatasetDetailSkeleton isTable={isTable} />}>
        <DetailPanel
          dataset={dataset}
          canEdit={isEditor}
          canEditData={canEditData}
          capabilities={capabilities}
          activeTab={activeTab}
          onTabChange={handleTabChange}
          resolveDraftValue={resolveDraftValue}
          stagePendingDraft={stagePendingDraft}
          handleDraftDirtyChange={handleDraftDirtyChange}
          onNavigateToValidationField={handleNavigateToValidationField}
          isTableExpanded={isDataTabExpanded}
          onToggleTableExpand={toggleDataTabExpand}
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

      {/* Dialogs */}
      {isAdmin && (
        <DatasetDeleteDialog
          dataset={dataset}
          open={activeDialog === 'delete'}
          onOpenChange={(open) => setActiveDialog(open ? 'delete' : null)}
        />
      )}

      {isEditor && !isVrt && (
        <Suspense fallback={null}>
          <ReuploadDialog
            dataset={dataset}
            open={activeDialog === 'reupload'}
            onOpenChange={(open) => setActiveDialog(open ? 'reupload' : null)}
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
            <AlertDialogAction variant="destructive" onClick={() => blocker.proceed?.()}>
              {t('unsaved.leave', { defaultValue: 'Leave' })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}
