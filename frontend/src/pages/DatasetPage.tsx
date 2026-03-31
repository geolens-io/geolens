import { useState, useCallback, useEffect, useRef } from 'react';
import { useParams, Link } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowLeft, Download, Trash2, Upload, Globe, GlobeLock, Layers, Eye, EyeOff, ShieldAlert, Minimize2, Maximize2 } from 'lucide-react';
import { toast } from 'sonner';
import { PageShell } from '@/components/layout/PageShell';
import { ErrorState } from '@/components/layout/ErrorState';
import { useDataset, useUpdateDataset, useUpdatePublicationStatus, useValidation } from '@/hooks/use-dataset';
import { useDatasetEditCapabilities } from '@/hooks/use-dataset-edit-capabilities';
import { useDraftEditing } from '@/hooks/use-draft-editing';
import { useHeroState } from '@/hooks/use-hero-state';
import { useAllSettings } from '@/hooks/use-settings';
import { useAuthStore } from '@/stores/auth-store';
import { useDrawingStore } from '@/stores/drawing-store';
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
import { getValidationNavigationAction } from '@/lib/dataset-validation-navigation';
import { formatRelativeDate } from '@/lib/format';
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


export function DatasetPage() {
  const { t } = useTranslation('dataset');
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [pollInterval, setPollInterval] = useState<number | false>(false);
  const { data: dataset, isLoading, error } = useDataset(id ?? '', {
    refetchInterval: pollInterval,
  });
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [reuploadOpen, setReuploadOpen] = useState(false);
  const [vrtOpen, setVrtOpen] = useState(false);
  const [unpublishConfirmOpen, setUnpublishConfirmOpen] = useState(false);
  const updatePublicationStatus = useUpdatePublicationStatus();
  const token = useAuthStore((s) => s.token);
  const { data: validationData } = useValidation(token ? id : undefined);
  const { data: allSettings } = useAllSettings({ enabled: !!token });
  const [activeTab, setActiveTab] = useState(getInitialTab);
  const [pendingNavigationAnchor, setPendingNavigationAnchor] = useState<string | null>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const selectedFeatureGid = useDrawingStore((s) => s.selectedFeature?.gid ?? null);
  const [readOnlyFeatureGid, setReadOnlyFeatureGid] = useState<number | null>(null);
  const [isHeroExpanded, setIsHeroExpanded] = useState(true);
  const [isDataTabExpanded, setIsDataTabExpanded] = useState(false);
  const toggleDataTabExpand = useCallback(() => setIsDataTabExpanded((prev) => !prev), []);
  const effectiveGid = selectedFeatureGid ?? readOnlyFeatureGid;
  const isAdmin = useAuthStore((s) => s.isAdmin());
  const isEditor = useAuthStore((s) => s.isEditor());
  const capabilities = useDatasetEditCapabilities();
  const isDrawing = useDrawingStore((s) => s.isDrawing);
  const isGeometryEditDirty = useDrawingStore((s) => s.isEditDirty);
  useDocumentTitle(dataset?.title ?? 'Dataset');

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

  // Clear read-only selection when editing mode activates
  useEffect(() => {
    if (selectedFeatureGid != null) {
      setReadOnlyFeatureGid(null);
    }
  }, [selectedFeatureGid]);

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
    if (!normalizedLegacyHash || normalizedLegacyHash === hash) return;

    const nextUrl = `${window.location.pathname}${window.location.search}#${normalizedLegacyHash}`;
    window.history.replaceState(window.history.state, '', nextUrl);
  }, []);

  // Poll dataset when VRT is regenerating so the banner auto-clears
  useEffect(() => {
    const status = dataset?.raster?.status;
    setPollInterval(status === 'regenerating' ? 5_000 : false);
  }, [dataset?.raster?.status]);

  useEffect(() => {
    if (!pendingNavigationAnchor) return;

    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    let frameId = 0;

    const focusAnchor = () => {
      const target = document.querySelector<HTMLElement>(
        `[data-field-anchor="${pendingNavigationAnchor}"]`,
      );

      if (!target) {
        timeoutId = setTimeout(() => {
          const retryTarget = document.querySelector<HTMLElement>(
            `[data-field-anchor="${pendingNavigationAnchor}"]`,
          );
          if (!retryTarget) {
            setPendingNavigationAnchor(null);
            return;
          }

          retryTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });
          const focusable =
            retryTarget.matches('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
              ? retryTarget
              : retryTarget.querySelector<HTMLElement>(
                  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
                );
          focusable?.focus({ preventScroll: true });
          setPendingNavigationAnchor(null);
        }, 120);
        return;
      }

      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      const focusable =
        target.matches('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
          ? target
          : target.querySelector<HTMLElement>(
              'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
            );
      focusable?.focus({ preventScroll: true });
      setPendingNavigationAnchor(null);
    };

    frameId = requestAnimationFrame(() => {
      focusAnchor();
    });

    return () => {
      cancelAnimationFrame(frameId);
      if (timeoutId) clearTimeout(timeoutId);
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
  const requireMetadata = allSettings?.tabs?.general?.find((s: { key: string }) => s.key === 'require_metadata_for_publish')?.value ?? false;

  const handlePublishToggle = async () => {
    if (!id) return;
    if (isPublished) {
      setUnpublishConfirmOpen(true);
      return;
    }
    if (requireMetadata && hasValidationErrors) {
      toast.error(t('publish.validationBlocker', { defaultValue: 'Resolve validation issues before publishing' }));
      return;
    }
    try {
      const steps = ['ready', 'internal', 'published'];
      for (const step of steps) {
        await updatePublicationStatus.mutateAsync({ datasetId: id, status: step });
      }
      toast.success(t('publish.success'));
    } catch {
      toast.error(t('publish.failed'));
    }
  };

  const handleUnpublish = async () => {
    if (!id) return;
    try {
      const steps = ['internal', 'ready', 'draft'];
      for (const step of steps) {
        await updatePublicationStatus.mutateAsync({ datasetId: id, status: step });
      }
      toast.success(t('publish.unpublished'));
    } catch {
      toast.error(t('publish.failed'));
    } finally {
      setUnpublishConfirmOpen(false);
    }
  };

  const statsLine = (
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
                <span>{dataset.feature_count.toLocaleString()} {isTable ? 'rows' : 'features'}</span>
              </>
            )}
            {dataset.srid && (
              <>
                <Sep />
                <span>EPSG:{dataset.srid}</span>
              </>
            )}
          </>
        ) : dataset.record_type === 'raster_dataset' ? (
          <>
            {dataset.raster?.band_count != null && (
              <>
                <Sep />
                <span>{dataset.raster.band_count} bands</span>
              </>
            )}
            {dataset.raster?.gsd != null && (
              <>
                <Sep />
                <span>{dataset.raster.gsd} m</span>
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
                <span>{dataset.raster.vrt_type === 'band_stack' ? 'Band Stack' : 'Mosaic'}</span>
              </>
            )}
            {dataset.raster?.source_count != null && (
              <>
                <Sep />
                <span>{dataset.raster.source_count} sources</span>
              </>
            )}
            {dataset.raster?.band_count != null && (
              <>
                <Sep />
                <span>{dataset.raster.band_count} bands</span>
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
          {dataset.visibility === 'public' ? <Eye className="mr-1 h-3 w-3" /> : dataset.visibility === 'restricted' ? <ShieldAlert className="mr-1 h-3 w-3" /> : <EyeOff className="mr-1 h-3 w-3" />}
          {dataset.visibility}
        </Badge>
        <Sep />
        <span>Updated {formatRelativeDate(dataset.updated_at)}</span>
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
      disabled: updatePublicationStatus.isPending,
    },
    {
      id: 'reupload',
      label: t('actions.reupload'),
      icon: Upload,
      onSelect: () => setReuploadOpen(true),
      priority: 10,
      visible: isEditor && !isVrt,
      variant: 'outline',
    },
    {
      id: 'create-vrt',
      label: t('actions.createVrt', { defaultValue: 'Create VRT' }),
      icon: Layers,
      onSelect: () => setVrtOpen(true),
      priority: 11,
      visible: isRaster && isEditor,
    },
    {
      id: 'delete',
      label: t('actions.delete'),
      icon: Trash2,
      onSelect: () => setDeleteOpen(true),
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
              <Button variant="default" size="sm" onClick={() => downloadCog(dataset.id, dataset.title)}>
                <Download className="mr-1 size-3" />
                {t('actions.downloadCog', { defaultValue: 'Download COG' })}
              </Button>
            )}
            <ConnectDropdown dataset={dataset} />
          </div>
        }
      />

      {/* Hero Data Grid for table datasets (no map) */}
      {isTable && (
        <div className="rounded-lg border shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-3 py-1.5 bg-muted/30 border-b">
            <span className="text-xs text-muted-foreground font-medium">
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
            <DataTab datasetId={id!} canEdit={isEditor} />
          </div>
        </div>
      )}

      {/* Hero Map -- visible for all spatial dataset types */}
      {!isDataTabExpanded && !isTable && (
        <div
          ref={mapContainerRef}
          data-field-anchor="dataset_map"
          tabIndex={-1}
          className={cn(
            'rounded-lg border shadow-sm overflow-hidden relative',
            isDrawing ? 'h-[60vh]' : 'h-64 lg:h-80'
          )}
        >
          {isRasterOrVrt && heroState === 'loading' && (
            <Skeleton data-testid="hero-skeleton" className="absolute inset-0 z-10 rounded-lg" />
          )}
          <DatasetMap
            key={isRasterOrVrt ? mapKey : undefined}
            bbox={bbox}
            tableName={dataset.table_name}
            geometryType={dataset.geometry_type}
            datasetId={id}
            columnInfo={dataset.column_info}
            containerRef={mapContainerRef}
            canEdit={isEditor && !isRaster && !isVrt && !isTable}
            recordType={dataset.record_type}
            rasterTileUrl={dataset.raster?.tile_url}
            tileVersion={dataset.updated_at}
            onFeatureClick={setReadOnlyFeatureGid}
            {...(isRasterOrVrt ? {
              onMapReady,
              onTileError,
            } : {})}
          />
          {dataset.record_type === 'raster_dataset' && !dataset.raster?.tile_url && heroState === 'loaded' && (
            <div className="absolute bottom-2 left-2 z-10 px-2 py-1 rounded bg-muted/80 text-xs text-muted-foreground">
              No raster tiles available
            </div>
          )}
          {isRasterOrVrt && heroState === 'error' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-background/80 rounded-lg z-10">
              <AlertTriangle className="size-8 text-destructive mb-2" />
              <p className="text-sm text-muted-foreground mb-3">Preview unavailable</p>
              {retryCount < 3 ? (
                <Button size="sm" onClick={handleRetry}>Retry</Button>
              ) : (
                <p className="text-xs text-muted-foreground">Tiles may still be processing</p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Raster Quick Facts Strip */}
      {!isDataTabExpanded && dataset.record_type === 'raster_dataset' && dataset.raster && (
        <div className="flex items-center gap-3 px-3 py-2 rounded-lg border bg-muted/30 text-sm overflow-x-auto">
          {dataset.raster.band_count != null && (
            <div><span className="text-muted-foreground">Bands</span> <span className="font-medium">{dataset.raster.band_count}</span></div>
          )}
          {(dataset.raster.res_x != null || dataset.raster.gsd != null) && (
            <div>
              <span className="text-muted-foreground">Resolution</span>{' '}
              <span className="font-medium">{dataset.raster.gsd ? `${dataset.raster.gsd} m` : `${dataset.raster.res_x?.toFixed(6)}`}</span>
            </div>
          )}
          {dataset.raster.width != null && dataset.raster.height != null && (
            <div><span className="text-muted-foreground">Dimensions</span> <span className="font-medium">{dataset.raster.width} x {dataset.raster.height} px</span></div>
          )}
          {dataset.raster.compression && (
            <div><span className="text-muted-foreground">Format</span> <span className="font-medium">{dataset.raster.compression}</span></div>
          )}
        </div>
      )}

      {/* Tabbed content — tabs shown are driven by record_type */}
      <DetailPanel
        dataset={dataset}
        canEdit={isEditor}
        capabilities={capabilities}
        datasetId={id!}
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
        onSaveAll={() => { savePendingDrafts(); }}
        onCancelAll={discardPendingDrafts}
        isSaving={isSavingPendingEdits}
      />

      {/* Dialogs */}
      {isAdmin && (
        <DatasetDeleteDialog
          dataset={dataset}
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
        />
      )}

      {isEditor && !isVrt && (
        <ReuploadDialog
          dataset={dataset}
          open={reuploadOpen}
          onOpenChange={setReuploadOpen}
        />
      )}

      {isRaster && isEditor && (
        <VrtCreateDialog
          open={vrtOpen}
          onOpenChange={setVrtOpen}
          initialSourceId={dataset.id}
        />
      )}

      <AlertDialog open={unpublishConfirmOpen} onOpenChange={setUnpublishConfirmOpen}>
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
