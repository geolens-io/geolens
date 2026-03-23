import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { useParams, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowLeft, Download, Trash2, Upload, Globe, GlobeLock, Layers, Eye, EyeOff, ShieldAlert } from 'lucide-react';
import { toast } from 'sonner';
import { PageShell } from '@/components/layout/PageShell';
import { ErrorState } from '@/components/layout/ErrorState';
import { useDataset, useUpdateDataset, useUpdatePublicationStatus, useValidation } from '@/hooks/use-dataset';
import { useDatasetEditCapabilities } from '@/hooks/use-dataset-edit-capabilities';
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
import { VectorDetailPanel } from '@/components/dataset/panels/VectorDetailPanel';
import { RasterDetailPanel } from '@/components/dataset/panels/RasterDetailPanel';
import { VrtDetailPanel } from '@/components/dataset/panels/VrtDetailPanel';
import { CollectionDetailPanel } from '@/components/dataset/panels/CollectionDetailPanel';
import { PendingEditsBar } from '@/components/dataset/PendingEditsBar';
import { ConnectDropdown } from '@/components/dataset/ConnectDropdown';
import { AddToMapButton } from '@/components/dataset/AddToMapButton';
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
import type { DatasetUpdateRequest } from '@/types/api';

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

type PendingDraftField =
  | 'summary'
  | 'lineage_summary'
  | 'source_url'
  | 'source_organization'
  | 'update_frequency'
  | 'usage_constraints'
  | 'access_constraints'
  | 'sensitivity_classification'
  | 'quality_statement';
type PendingDrafts = Partial<Record<PendingDraftField, string | null>>;

function normalizeDraftValue(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function normalizeDatasetValue(value: string | null | undefined): string | null {
  const normalized = value?.trim() ?? '';
  return normalized.length > 0 ? normalized : null;
}

export function DatasetPage() {
  const { t } = useTranslation('dataset');
  const { id } = useParams<{ id: string }>();
  const [pollInterval, setPollInterval] = useState<number | false>(false);
  const { data: dataset, isLoading, error } = useDataset(id ?? '', {
    refetchInterval: pollInterval,
  });
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [reuploadOpen, setReuploadOpen] = useState(false);
  const [vrtOpen, setVrtOpen] = useState(false);
  const [unpublishConfirmOpen, setUnpublishConfirmOpen] = useState(false);
  const updatePublicationStatus = useUpdatePublicationStatus();
  const { data: validationData } = useValidation(id);
  const { data: allSettings } = useAllSettings();
  const [activeTab, setActiveTab] = useState(getInitialTab);
  const [pendingDrafts, setPendingDrafts] = useState<PendingDrafts>({});
  const [dirtyFields, setDirtyFields] = useState<Set<PendingDraftField>>(() => new Set());
  const [isSavingPendingEdits, setIsSavingPendingEdits] = useState(false);
  const [pendingNavigationAnchor, setPendingNavigationAnchor] = useState<string | null>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const selectedFeatureGid = useDrawingStore((s) => s.selectedFeature?.gid ?? null);
  const [readOnlyFeatureGid, setReadOnlyFeatureGid] = useState<number | null>(null);
  const effectiveGid = selectedFeatureGid ?? readOnlyFeatureGid;
  const isAdmin = useAuthStore((s) => s.isAdmin());
  const isEditor = useAuthStore((s) => s.isEditor());
  const capabilities = useDatasetEditCapabilities();
  const isDrawing = useDrawingStore((s) => s.isDrawing);
  const isGeometryEditDirty = useDrawingStore((s) => s.isEditDirty);
  const updateDataset = useUpdateDataset();
  useDocumentTitle(dataset?.title ?? 'Dataset');

  // Clear read-only selection when editing mode activates
  useEffect(() => {
    if (selectedFeatureGid != null) {
      setReadOnlyFeatureGid(null);
    }
  }, [selectedFeatureGid]);

  // Hero state machine for raster/VRT previews
  type HeroState = 'loading' | 'loaded' | 'error';
  const isRasterOrVrt = dataset?.record_type === 'raster_dataset' || dataset?.record_type === 'vrt_dataset';
  const [heroState, setHeroState] = useState<HeroState>('loading');
  const [retryCount, setRetryCount] = useState(0);
  const [mapKey, setMapKey] = useState(0);

  const handleTabChange = useCallback((value: string) => {
    setActiveTab(value);
    window.location.hash = value;
  }, []);

  const handleSaveName = useCallback(
    async (newName: string) => {
      if (!id) return;
      await updateDataset.mutateAsync({ datasetId: id, data: { title: newName } });
    },
    [id, updateDataset],
  );

  const stagePendingDraft = useCallback(
    (field: PendingDraftField, value: string) => {
      const normalizedNext = normalizeDraftValue(value);
      const currentDatasetValue = normalizeDatasetValue(
        (dataset?.[field] as string | null | undefined) ?? null,
      );

      setPendingDrafts((prev) => {
        const next = { ...prev };
        if (normalizedNext === currentDatasetValue) {
          delete next[field];
          return next;
        }
        next[field] = normalizedNext;
        return next;
      });
    },
    [dataset],
  );

  const handleDraftDirtyChange = useCallback((field: PendingDraftField, isDirty: boolean) => {
    setDirtyFields((prev) => {
      const next = new Set(prev);
      if (isDirty) {
        next.add(field);
      } else {
        next.delete(field);
      }
      return next;
    });
  }, []);

  const resolveDraftValue = useCallback(
    (field: PendingDraftField) => {
      const staged = pendingDrafts[field];
      if (staged !== undefined) {
        return staged ?? '';
      }
      return (dataset?.[field] as string | null | undefined) ?? '';
    },
    [dataset, pendingDrafts],
  );

  const pendingFields = useMemo(() => {
    const fields = new Set<PendingDraftField>(Object.keys(pendingDrafts) as PendingDraftField[]);
    for (const field of dirtyFields) {
      fields.add(field);
    }
    return fields;
  }, [dirtyFields, pendingDrafts]);

  const metadataPendingCount = pendingFields.size;
  const hasUnsavedChanges = metadataPendingCount > 0 || isGeometryEditDirty;

  const savePendingDrafts = useCallback(async (): Promise<boolean> => {
    if (!id) return false;

    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
      await new Promise((resolve) => setTimeout(resolve, 0));
    }

    const entries = Object.entries(pendingDrafts) as Array<[PendingDraftField, string | null]>;
    if (entries.length === 0) {
      return true;
    }

    const payload = entries.reduce<Record<PendingDraftField, string | null>>((acc, [field, value]) => {
      acc[field] = value;
      return acc;
    }, {} as Record<PendingDraftField, string | null>);

    setIsSavingPendingEdits(true);
    try {
      await updateDataset.mutateAsync({ datasetId: id, data: payload as DatasetUpdateRequest });
      setPendingDrafts({});
      setDirtyFields(new Set());
      toast.success(
        t('affordances.pending.saved', {
          defaultValue: 'Changes saved.',
        }),
      );
      if (isGeometryEditDirty) {
        toast.info(
          t('affordances.pending.geometryHint', {
            defaultValue: 'Field changes saved. Save geometry changes from the map toolbar.',
          }),
        );
      }
      return true;
    } catch {
      toast.error(
        t('affordances.pending.saveFailed', {
          defaultValue: 'Failed to save pending edits.',
        }),
      );
      return false;
    } finally {
      setIsSavingPendingEdits(false);
    }
  }, [id, isGeometryEditDirty, pendingDrafts, t, updateDataset]);

  const discardPendingDrafts = useCallback(() => {
    setPendingDrafts({});
    setDirtyFields(new Set());
    toast.message(
      t('affordances.pending.canceled', {
        defaultValue: 'All changes discarded.',
      }),
    );
  }, [t]);

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

  // 10s timeout: if raster/VRT map never calls onMapReady, show error
  useEffect(() => {
    if (!isRasterOrVrt || heroState !== 'loading') return;
    const timer = setTimeout(() => {
      setHeroState('error');
    }, 10_000);
    return () => clearTimeout(timer);
  }, [heroState, isRasterOrVrt]);

  // Retry handler for raster/VRT hero error state
  const handleRetry = useCallback(() => {
    setRetryCount(prev => prev + 1);
    setHeroState('loading');
    setMapKey(prev => prev + 1);
  }, []);

  // Reset hero state when dataset changes
  useEffect(() => {
    setHeroState('loading');
    setRetryCount(0);
    setMapKey(0);
  }, [id]);

  // Raster with no tile_url: skip to 'loaded' immediately (no tiles to wait for)
  useEffect(() => {
    if (dataset?.record_type === 'raster_dataset' && !dataset.raster?.tile_url) {
      setHeroState('loaded');
    }
  }, [dataset?.record_type, dataset?.raster?.tile_url]);

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
    return <DatasetDetailSkeleton />;
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

  const Sep = () => <span className="text-muted-foreground/50">·</span>;

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
                <span>{dataset.feature_count.toLocaleString()} features</span>
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
            <AddToMapButton datasetId={dataset.id} datasetTitle={dataset.title} />
            {isRaster && dataset.raster?.connect && (
              <Button asChild variant="default" size="sm">
                <a href={`/api/datasets/${dataset.id}/download/cog`} download>
                  <Download className="mr-1 size-3" />
                  {t('actions.downloadCog', { defaultValue: 'Download COG' })}
                </a>
              </Button>
            )}
            <ConnectDropdown dataset={dataset} />
          </div>
        }
      />

      {/* Hero Data Grid for table datasets (no map) */}
      {isTable && (
        <div className="rounded-lg border shadow-sm overflow-hidden">
          <div className="h-[60vh]">
            <DataTab datasetId={id!} canEdit={isEditor} />
          </div>
        </div>
      )}

      {/* Hero Map -- visible for all spatial dataset types */}
      {!isTable && (
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
              onMapReady: () => setHeroState('loaded'),
              onTileError: () => setHeroState('error'),
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
      {dataset.record_type === 'raster_dataset' && dataset.raster && (
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

      {/* Type-specific tabbed content */}
      {dataset.record_type === 'raster_dataset' && (
        <RasterDetailPanel
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
        />
      )}
      {dataset.record_type === 'vrt_dataset' && (
        <VrtDetailPanel
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
        />
      )}
      {dataset.record_type === 'collection' && (
        <CollectionDetailPanel
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
        />
      )}
      {(dataset.record_type === 'vector_dataset' || dataset.record_type === 'table' || !dataset.record_type) && (
        <VectorDetailPanel
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
        />
      )}

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
