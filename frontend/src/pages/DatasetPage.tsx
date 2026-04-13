import { useState, useCallback, useEffect, useRef } from 'react';
import { useParams, Link } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Download, Trash2, Upload, Globe, GlobeLock, Layers, EyeOff, Minimize2, Maximize2, Database } from 'lucide-react';
import { toast } from 'sonner';
import { PageShell } from '@/components/layout/PageShell';
import { ErrorState } from '@/components/layout/ErrorState';
import { useDataset, useUpdateDataset, useUpdatePublicationStatus, useValidation } from '@/hooks/use-dataset';
import { useDatasetJobStatus } from '@/hooks/use-ingest';
import { IngestWarningsBanner } from '@/components/import/IngestWarningsBanner';
import { useDatasetEditCapabilities } from '@/hooks/use-dataset-edit-capabilities';
import { useDraftEditing } from '@/hooks/use-draft-editing';
import { useHeroState } from '@/hooks/use-hero-state';
import { useAllSettings } from '@/hooks/use-settings';
import { useAuthStore } from '@/stores/auth-store';
import { useDrawingStore } from '@/stores/drawing-store';
import { DatasetDeleteDialog } from '@/components/dataset/DatasetDeleteDialog';
import { ReuploadDialog } from '@/components/dataset/ReuploadDialog';
import { DatasetHeroMap } from '@/pages/components/DatasetHeroMap';
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
import { MapErrorBoundary } from '@/components/error';
import { getValidationNavigationAction } from '@/lib/dataset-validation-navigation';
import { formatNumber } from '@/lib/format';
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
import type { DatasetResponse } from '@/types/api';
import { DatasetStatsLine } from '@/pages/components/DatasetStatsLine';
import { downloadCog } from '@/api/datasets';

const VALID_TABS = ['overview', 'metadata', 'data', 'structure', 'sources', 'members', 'access'] as const;

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
  const [activeDialog, setActiveDialog] = useState<'delete' | 'reupload' | 'vrt' | 'unpublish' | null>(null);
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

  // Derived ground-sampling-distance. Backend `RasterMetadata` exposes
  // `res_x` and `res_y` but not a pre-computed `gsd`, so mirror the
  // backend's models.py formula (min of absolute pixel resolutions)
  // here. Returns null if either resolution is unknown.
  const rasterGsd: number | null =
    dataset.raster?.res_x != null && dataset.raster?.res_y != null
      ? Math.min(Math.abs(dataset.raster.res_x), Math.abs(dataset.raster.res_y))
      : null;

  const isPublished = dataset.record_status === 'published';
  const hasValidationErrors = validationData ? validationData.errors.length > 0 : false;
  const requireMetadata = allSettings?.tabs?.general?.find((s: { key: string }) => s.key === 'require_metadata_for_publish')?.value ?? false;

  const PUBLISH_CHAIN = ['ready', 'internal', 'published'] as const;
  const UNPUBLISH_CHAIN = ['internal', 'ready', 'draft'] as const;

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
    // Only transition the steps not yet completed based on current status
    const currentStatus = dataset.record_status;
    const startIdx = PUBLISH_CHAIN.indexOf(currentStatus as typeof PUBLISH_CHAIN[number]);
    const steps = startIdx === -1 ? PUBLISH_CHAIN : PUBLISH_CHAIN.slice(startIdx + 1);
    try {
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
    // Only transition the steps not yet completed based on current status
    const currentStatus = dataset.record_status;
    const startIdx = UNPUBLISH_CHAIN.indexOf(currentStatus as typeof UNPUBLISH_CHAIN[number]);
    const steps = startIdx === -1 ? UNPUBLISH_CHAIN : UNPUBLISH_CHAIN.slice(startIdx + 1);
    try {
      for (const step of steps) {
        await updatePublicationStatus.mutateAsync({ datasetId: id, status: step });
      }
      toast.success(t('publish.unpublished'));
    } catch {
      toast.error(t('publish.failed'));
    } finally {
      setActiveDialog(null);
    }
  };

  const statsLine = <DatasetStatsLine dataset={dataset} rasterGsd={rasterGsd} />;

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
              <DataTab datasetId={id!} canEdit={isEditor} />
            </div>
          </div>
        </div>
      )}

      {/* Hero Map -- visible for all spatial dataset types */}
      {!isDataTabExpanded && !isTable && (
        <MapErrorBoundary>
          <DatasetHeroMap
            dataset={dataset}
            datasetId={id}
            bbox={bbox}
            isEditor={isEditor}
            isDrawing={isDrawing}
            mapContainerRef={mapContainerRef}
            onFeatureClick={setReadOnlyFeatureGid}
            isRasterOrVrt={isRasterOrVrt}
            heroState={heroState}
            retryCount={retryCount}
            mapKey={mapKey}
            handleRetry={handleRetry}
            onMapReady={onMapReady}
            onTileError={onTileError}
          />
        </MapErrorBoundary>
      )}

      {/* Raster Quick Facts Strip */}
      {!isDataTabExpanded && dataset.record_type === 'raster_dataset' && dataset.raster && (
        <div className="flex items-center gap-3 px-3 py-2 rounded-lg border bg-muted/30 text-sm overflow-x-auto">
          {dataset.raster.band_count != null && (
            <div><span className="text-muted-foreground">{t('raster.bands')}</span> <span className="font-medium">{dataset.raster.band_count}</span></div>
          )}
          {(dataset.raster.res_x != null || rasterGsd != null) && (
            <div>
              <span className="text-muted-foreground">{t('raster.resolution')}</span>{' '}
              <span className="font-medium">{rasterGsd != null ? `${rasterGsd} m` : `${dataset.raster.res_x?.toFixed(6)}`}</span>
            </div>
          )}
          {dataset.raster.width != null && dataset.raster.height != null && (
            <div><span className="text-muted-foreground">{t('raster.dimensions')}</span> <span className="font-medium">{dataset.raster.width} x {dataset.raster.height} px</span></div>
          )}
          {dataset.raster.compression && (
            <div><span className="text-muted-foreground">{t('raster.format')}</span> <span className="font-medium">{dataset.raster.compression}</span></div>
          )}
        </div>
      )}

      {/* Tabbed content — tabs shown are driven by record_type */}
      <DetailPanel
        dataset={dataset}
        canEdit={isEditor}
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
        onSaveAll={async () => {
          // savePendingDrafts returns Promise<boolean> (true on success)
          // but PendingEditsBar only needs a void/Promise<void> handler,
          // so the boolean result is intentionally discarded here.
          await savePendingDrafts();
        }}
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
