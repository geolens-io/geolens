import { useState, useCallback, useEffect, useRef } from 'react';
import { useParams, Link } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowLeft, Download, Trash2, Upload, Globe, GlobeLock, Layers, Eye, EyeOff, ShieldAlert, Minimize2, Maximize2, Database, Mountain } from 'lucide-react';
import { toast } from 'sonner';
import { PageShell } from '@/components/layout/PageShell';
import { ErrorState } from '@/components/layout/ErrorState';
import { useDataset, useUpdateDataset, useUpdatePublicationStatus, useValidation } from '@/components/dataset/hooks/use-dataset';
import { useDatasetJobStatus } from '@/components/import/hooks/use-ingest';
import { IngestWarningsBanner } from '@/components/import/IngestWarningsBanner';
import { useDatasetEditCapabilities } from '@/components/dataset/hooks/use-dataset-edit-capabilities';
import { useDraftEditing } from '@/components/dataset/hooks/use-draft-editing';
import { useFeatureGid } from '@/components/dataset/hooks/use-feature-gid';
import { useHeroState } from '@/components/dataset/hooks/use-hero-state';
import { useFeatureFlags } from '@/hooks/use-settings';
import { useAuthStore } from '@/stores/auth-store';
import { useDrawingStore } from '@/components/drawing/drawing-store';
import { DatasetDeleteDialog } from '@/components/dataset/DatasetDeleteDialog';
import { ReuploadDialog } from '@/components/dataset/ReuploadDialog';
import { DatasetMap } from '@/components/dataset/DatasetMap';
import { DatasetDetailSkeleton } from '@/components/dataset/DatasetDetailSkeleton';
import {
  DatasetDetailHeader,
  type DatasetDetailHeaderAction,
} from '@/components/dataset/DatasetDetailHeader';
import { DataTab } from '@/components/dataset/tabs/DataTab';
import { RelatedRecordsPanel } from '@/components/dataset/RelatedRecordsPanel';
import { DetailPanel } from '@/components/dataset/panels/DetailPanel';
import { PendingEditsBar } from '@/components/dataset/PendingEditsBar';
import { ConnectDropdown } from '@/components/dataset/ConnectDropdown';
import { AddToMapButton } from '@/components/dataset/AddToMapButton';
import { AuthPrompt } from '@/components/auth/AuthPrompt';
import { VrtCreateDialog } from '@/components/import/VrtCreateDialog';
import { RecordTypeBadge } from '@/components/search/RecordTypeBadge';
import { DatasetStatsBar } from '@/components/dataset/DatasetStatsBar';
import { MapErrorBoundary } from '@/components/error';
import { getValidationNavigationAction } from '@/lib/dataset-validation-navigation';
import { formatRelativeDate, formatNumber } from '@/lib/format';
import { findElevationColumn, computeRasterGsd } from '@/lib/geo-utils';
import { getRecordStatusLabel, getGeometryTypeLabel } from '@/i18n/labels';
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
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { visibilityColors } from '@/lib/status-colors';
import type { DatasetResponse } from '@/types/api';
import { downloadCog } from '@/api/datasets';

const VALID_TABS = ['overview', 'metadata', 'data', 'structure', 'sources', 'members', 'access'] as const;
const PUBLISH_CHAIN = ['ready', 'internal', 'published'] as const;
const UNPUBLISH_CHAIN = ['internal', 'ready', 'draft'] as const;

const Sep = () => <span className="text-muted-foreground/50">·</span>;


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

function RecordTypeStats({ dataset, t }: { dataset: DatasetResponse; t: ReturnType<typeof import('react-i18next').useTranslation>['t'] }) {
  const isTable = dataset.record_type === 'table';
  const rasterGsd = computeRasterGsd(dataset.raster?.res_x, dataset.raster?.res_y);

  return (
    <>
      <div className="flex items-center gap-1.5 flex-wrap">
        <RecordTypeBadge recordType={dataset.record_type} />
        {dataset.record_type === 'vector_dataset' || dataset.record_type === 'table' || !dataset.record_type ? (
          <>
            {dataset.geometry_type && (
              <>
                <Sep />
                <span>{getGeometryTypeLabel(t, dataset.geometry_type)}</span>
              </>
            )}
            {dataset.feature_count != null && (
              <>
                <Sep />
                <span>{formatNumber(dataset.feature_count)} {isTable ? (dataset.feature_count === 1 ? 'row' : 'rows') : (dataset.feature_count === 1 ? 'feature' : 'features')}</span>
              </>
            )}
            {dataset.srid && (
              <>
                <Sep />
                <span>EPSG:{dataset.srid}</span>
              </>
            )}
            {dataset.is_3d && (
              <>
                <Sep />
                <span className="font-medium">3D</span>
                {dataset.z_min != null && dataset.z_max != null && (
                  <span className="ml-1 text-muted-foreground">
                    Z: {dataset.z_min.toFixed(1)} to {dataset.z_max.toFixed(1)}
                  </span>
                )}
              </>
            )}
            {!dataset.is_3d && findElevationColumn(dataset.column_info) && (
              <>
                <Sep />
                <span className="inline-flex items-center gap-1 text-muted-foreground">
                  <Mountain className="h-3.5 w-3.5" />
                  {t('page.hasElevation', { defaultValue: 'Elevation' })}
                </span>
              </>
            )}
          </>
        ) : dataset.record_type === 'raster_dataset' ? (
          <>
            {dataset.raster?.band_count != null && (
              <>
                <Sep />
                <span>{dataset.raster.band_count} {dataset.raster.band_count === 1 ? t('raster.band', { defaultValue: 'band' }) : t('raster.bands').toLowerCase()}</span>
              </>
            )}
            {rasterGsd != null && (
              <>
                <Sep />
                <span>{rasterGsd} m</span>
              </>
            )}
            {dataset.raster?.epsg && (
              <>
                <Sep />
                <span>EPSG:{dataset.raster.epsg}</span>
              </>
            )}
          </>
        ) : dataset.record_type === 'vrt_dataset' ? (
          <>
            {dataset.raster?.vrt_type && (
              <>
                <Sep />
                <span>{dataset.raster.vrt_type === 'band_stack' ? t('raster.bandStack') : t('raster.mosaic')}</span>
              </>
            )}
            {dataset.raster?.source_count != null && (
              <>
                <Sep />
                <span>{dataset.raster.source_count} {dataset.raster.source_count === 1 ? 'source' : 'sources'}</span>
              </>
            )}
            {dataset.raster?.band_count != null && (
              <>
                <Sep />
                <span>{dataset.raster.band_count} {dataset.raster.band_count === 1 ? 'band' : 'bands'}</span>
              </>
            )}
            {dataset.raster?.epsg && (
              <>
                <Sep />
                <span>EPSG:{dataset.raster.epsg}</span>
              </>
            )}
          </>
        ) : null}
      </div>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span>{getRecordStatusLabel(t, dataset.record_status)}</span>
        <Sep />
        <Badge variant="outline" className={cn('text-xs capitalize', visibilityColors[dataset.visibility] ?? '')}>
          {dataset.visibility === 'public' ? <Eye className="me-1 h-3 w-3" /> : dataset.visibility === 'restricted' ? <ShieldAlert className="me-1 h-3 w-3" /> : <EyeOff className="me-1 h-3 w-3" />}
          {dataset.visibility}
        </Badge>
        <Sep />
        <span>Updated {formatRelativeDate(dataset.updated_at)}</span>
      </div>
    </>
  );
}

function TableHero({
  dataset,
  isHeroExpanded,
  setIsHeroExpanded,
  datasetId,
  isEditor,
  t,
}: {
  dataset: DatasetResponse;
  isHeroExpanded: boolean;
  setIsHeroExpanded: React.Dispatch<React.SetStateAction<boolean>>;
  datasetId: string;
  isEditor: boolean;
  t: typeof import('react-i18next').useTranslation extends (...a: never[]) => { t: infer T } ? T : never;
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-lg border bg-muted/20 px-4 py-4 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
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
          {dataset.feature_count != null && (
            <Badge variant="secondary" className="self-start text-xs lg:self-center">
              {formatNumber(dataset.feature_count)} {dataset.feature_count === 1 ? 'row' : 'rows'}
            </Badge>
          )}
        </div>
      </div>
      <div className="rounded-lg border shadow-sm overflow-hidden">
        <div className="flex items-center justify-between border-b bg-muted/30 px-3 py-1.5">
          <span className="text-xs font-medium text-muted-foreground">
            {t('page.dataPreview', { defaultValue: 'Data Preview' })}
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0"
            onClick={() => setIsHeroExpanded(prev => !prev)}
            aria-label={isHeroExpanded ? 'Collapse data grid' : 'Expand data grid'}
          >
            {isHeroExpanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </Button>
        </div>
        <div className={isHeroExpanded ? 'h-[60vh]' : 'h-64'}>
          <DataTab datasetId={datasetId} canEdit={isEditor} />
        </div>
      </div>
    </div>
  );
}

export function DatasetPage() {
  const { t } = useTranslation('dataset');
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [pollInterval, setPollInterval] = useState<number | false>(false);
  const { data: dataset, isLoading, error } = useDataset(id ?? '', {
    refetchInterval: pollInterval,
  });
  const [activeDialog, setActiveDialog] = useState<'delete' | 'reupload' | 'vrt' | 'unpublish' | null>(null);
  const updatePublicationStatus = useUpdatePublicationStatus();
  const token = useAuthStore((s) => s.token);
  const { data: validationData } = useValidation(token ? id : undefined);
  const { data: featureFlags } = useFeatureFlags();
  const [activeTab, setActiveTab] = useState(getInitialTab);
  const [pendingNavigationAnchor, setPendingNavigationAnchor] = useState<string | null>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const { effectiveGid, setReadOnlyFeatureGid } = useFeatureGid();
  const [isHeroExpanded, setIsHeroExpanded] = useState(true);
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

  // Warn before navigating away with unsaved changes
  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [hasUnsavedChanges]);

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

  // Poll dataset when VRT is regenerating so the banner auto-clears
  useEffect(() => {
    const status = dataset?.raster?.status;
    setPollInterval(status === 'regenerating' ? 5_000 : false);
  }, [dataset?.raster?.status]);

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
              <ArrowLeft className="h-4 w-4" />
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

  const executeStatusChain = async (
    chain: readonly string[],
    currentStatus: string,
    successMsg: string,
  ) => {
    if (!id) return;
    const startIdx = chain.indexOf(currentStatus);
    const steps = startIdx === -1 ? chain : chain.slice(startIdx + 1);
    try {
      for (const step of steps) {
        await updatePublicationStatus.mutateAsync({ datasetId: id, status: step });
      }
      toast.success(successMsg);
    } catch {
      toast.error(t('publish.failed'));
    }
  };

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
    await executeStatusChain(PUBLISH_CHAIN, dataset.record_status, t('publish.success'));
  };

  const handleUnpublish = async () => {
    try {
      await executeStatusChain(UNPUBLISH_CHAIN, dataset.record_status, t('publish.unpublished'));
    } finally {
      setActiveDialog(null);
    }
  };

  const statsLine = <RecordTypeStats dataset={dataset} t={t} />;

  const headerActions: DatasetDetailHeaderAction[] = [
    {
      id: 'publish',
      label: isPublished ? t('publish.unpublish') : t('publish.publish'),
      icon: isPublished ? GlobeLock : Globe,
      onSelect: handlePublishToggle,
      priority: 5,
      visible: isEditor,
      disabled: updatePublicationStatus.isPending,
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
              <Button variant="default" size="sm" onClick={() => downloadCog(dataset.id)}>
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
      {isTable && (
        <TableHero
          dataset={dataset}
          isHeroExpanded={isHeroExpanded}
          setIsHeroExpanded={setIsHeroExpanded}
          datasetId={id!}
          isEditor={canEditData}
          t={t}
        />
      )}

      {/* Hero Map -- visible for all spatial dataset types */}
      {!isDataTabExpanded && !isTable && (
        <div
          ref={mapContainerRef}
          data-field-anchor="dataset_map"
          tabIndex={-1}
          className={cn(
            'rounded-lg border shadow-sm overflow-hidden relative',
            isDrawing ? 'h-[60vh]' : 'h-72 lg:h-96'
          )}
        >
          {isRasterOrVrt && heroState === 'loading' && (
            <Skeleton data-testid="hero-skeleton" className="absolute inset-0 z-10 rounded-lg" />
          )}
          <MapErrorBoundary>
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

      {/* Related records panel -- shown when a feature is selected (editing or read-only) */}
      {effectiveGid != null && (dataset.record_type === 'vector_dataset' || dataset.record_type === 'table' || !dataset.record_type) && (
        <RelatedRecordsPanel datasetId={id!} featureGid={effectiveGid} />
      )}

      <PendingEditsBar
        pendingCount={metadataPendingCount}
        onSaveAll={savePendingDrafts}
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
        <ReuploadDialog
          dataset={dataset}
          open={activeDialog === 'reupload'}
          onOpenChange={(open) => setActiveDialog(open ? 'reupload' : null)}
        />
      )}

      {isRaster && isEditor && (
        <VrtCreateDialog
          open={activeDialog === 'vrt'}
          onOpenChange={(open) => setActiveDialog(open ? 'vrt' : null)}
          initialSourceId={dataset.id}
        />
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
    </PageShell>
  );
}
