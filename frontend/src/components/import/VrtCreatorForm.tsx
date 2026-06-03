import { useState, useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueries } from '@tanstack/react-query';
import { AlertCircle, X, Search, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { apiFetch } from '@/api/client';
import { searchDatasets } from '@/api/search';
import { queryKeys } from '@/lib/query-keys';
import { useCreateVrt } from '@/components/import/hooks/use-ingest';
import { JobProgress } from '@/components/import/JobProgress';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { ApiError } from '@/api/client';
import type { OGCRecordResponse } from '@/types/api';

const VRT_MAX_SOURCES = 20;

type VrtType = 'mosaic' | 'band_stack';
type ResolutionStrategy = 'finest' | 'coarsest' | 'average';

interface ValidationErrors {
  [datasetId: string]: string[];
}

function validateSources(
  sources: OGCRecordResponse[],
  vrtType: VrtType,
): ValidationErrors {
  if (sources.length < 2) return {};
  const errors: ValidationErrors = {};
  const first = sources[0];

  for (let i = 1; i < sources.length; i++) {
    const src = sources[i];
    const errs: string[] = [];

    // CRS check
    if (src.properties.crs && first.properties.crs && src.properties.crs !== first.properties.crs) {
      errs.push('crs_mismatch');
    }

    if (vrtType === 'mosaic') {
      // Band count check (mosaic only)
      if (
        src.properties.band_count != null &&
        first.properties.band_count != null &&
        src.properties.band_count !== first.properties.band_count
      ) {
        errs.push('band_count_mismatch');
      }
    }

    // Dtype check
    if (src.properties.dtype && first.properties.dtype && src.properties.dtype !== first.properties.dtype) {
      errs.push('dtype_mismatch');
    }

    // Nodata check
    if (src.properties.nodata != null && first.properties.nodata != null && src.properties.nodata !== first.properties.nodata) {
      errs.push('nodata_inconsistent');
    }

    // Band stack grid alignment check
    if (vrtType === 'band_stack') {
      const widthMismatch =
        src.properties.width != null &&
        first.properties.width != null &&
        src.properties.width !== first.properties.width;
      const heightMismatch =
        src.properties.height != null &&
        first.properties.height != null &&
        src.properties.height !== first.properties.height;
      const resXMismatch =
        src.properties.res_x != null &&
        first.properties.res_x != null &&
        src.properties.res_x !== first.properties.res_x;
      const resYMismatch =
        src.properties.res_y != null &&
        first.properties.res_y != null &&
        src.properties.res_y !== first.properties.res_y;

      if (widthMismatch || heightMismatch || resXMismatch || resYMismatch) {
        errs.push('grid_misaligned');
      }
    }

    if (errs.length > 0) {
      errors[src.id] = errs;
    }
  }

  return errors;
}

function errorMessage(
  code: string,
  src: OGCRecordResponse,
  first: OGCRecordResponse,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  switch (code) {
    case 'crs_mismatch':
      return t('vrt.crsMismatch', { src: src.properties.crs, first: first.properties.crs });
    case 'band_count_mismatch':
      return t('vrt.bandMismatch', { src: src.properties.band_count, first: first.properties.band_count });
    case 'dtype_mismatch':
      return t('vrt.dtypeMismatch', { src: src.properties.dtype, first: first.properties.dtype });
    case 'nodata_inconsistent':
      return t('vrt.nodataMismatch');
    case 'grid_misaligned':
      return t('vrt.gridMismatch');
    default:
      return code;
  }
}

interface VrtCreatorFormProps {
  initialSourceId?: string;
  initialSourceIds?: string[];
  onCancel?: () => void;
}

export function VrtCreatorForm({ initialSourceId, initialSourceIds, onCancel }: VrtCreatorFormProps) {
  const { t } = useTranslation('import');
  const createVrtMutation = useCreateVrt();

  const [vrtType, setVrtType] = useState<VrtType>('mosaic');
  const [resolutionStrategy, setResolutionStrategy] = useState<ResolutionStrategy>('finest');
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [selectedSources, setSelectedSources] = useState<OGCRecordResponse[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const multiInitializedRef = useRef(false);

  // Pre-select source from query param
  const { data: initialSource, isError: initialSourceError } = useQuery({
    queryKey: queryKeys.ogcRecords.detail(initialSourceId!),
    queryFn: () =>
      apiFetch<OGCRecordResponse>(`/collections/datasets/items/${initialSourceId}`),
    enabled: !!initialSourceId,
  });

  useEffect(() => {
    if (initialSourceError) toast.error(t('vrt.loadSourceFailed'));
  }, [initialSourceError, t]);

  useEffect(() => {
    if (
      initialSource &&
      selectedSources.length === 0 &&
      initialSource.properties.record_type === 'raster_dataset'
    ) {
      setSelectedSources([initialSource]);
    }
  }, [initialSource]); // eslint-disable-line react-hooks/exhaustive-deps

  // Pre-select multiple sources when initialSourceIds is provided (multi-source flow)
  const multiSourceQueries = useQueries({
    queries: (initialSourceIds && !initialSourceId ? initialSourceIds : []).map((id) => ({
      queryKey: queryKeys.ogcRecords.detail(id),
      queryFn: () => apiFetch<OGCRecordResponse>(`/collections/datasets/items/${id}`),
      enabled: true,
    })),
  });

  useEffect(() => {
    if (!initialSourceIds || initialSourceIds.length === 0 || initialSourceId) return;
    if (multiInitializedRef.current) return;
    const allDone = multiSourceQueries.every((q) => q.isSuccess);
    if (!allDone) return;
    const rasterSources = multiSourceQueries
      .map((q) => q.data)
      .filter((d): d is OGCRecordResponse => !!d && d.properties.record_type === 'raster_dataset');
    if (rasterSources.length > 0 && selectedSources.length === 0) {
      multiInitializedRef.current = true;
      setSelectedSources(rasterSources);
    }
  }, [multiSourceQueries, initialSourceIds, initialSourceId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Surface multi-source load errors so they aren't silently swallowed
  const multiSourceErrorCount = multiSourceQueries.filter((q) => q.isError).length;
  useEffect(() => {
    if (multiSourceErrorCount > 0) {
      toast.error(t('vrt.loadSourcesFailed', { count: multiSourceErrorCount }));
    }
  }, [multiSourceErrorCount, t]);

  // Debounce search query
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(searchQuery);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // COG search query
  const { data: searchResults, isFetching: isSearchFetching, error: searchError } = useQuery({
    queryKey: queryKeys.cogSearch.results(debouncedQuery),
    queryFn: () =>
      searchDatasets({
        q: debouncedQuery,
        record_type: 'raster_dataset',
        limit: '10',
      }),
    enabled: debouncedQuery.length >= 2,
  });

  // Filter out already selected datasets
  const filteredResults = useMemo(() => {
    if (!searchResults) return [];
    const selectedIds = new Set(selectedSources.map((s) => s.id));
    return searchResults.features.filter((f) => !selectedIds.has(f.id));
  }, [searchResults, selectedSources]);

  // Validation errors
  const validationErrors = useMemo(
    () => validateSources(selectedSources, vrtType),
    [selectedSources, vrtType],
  );

  const hasErrors = Object.keys(validationErrors).length > 0;
  const isSubmitDisabled =
    selectedSources.length < 2 ||
    hasErrors ||
    title.trim().length === 0 ||
    createVrtMutation.isPending;

  function resetForm() {
    setVrtType('mosaic');
    setResolutionStrategy('finest');
    setTitle('');
    setSummary('');
    setSelectedSources([]);
    setSearchQuery('');
    setDebouncedQuery('');
    setIsDropdownOpen(false);
  }

  function handleAddSource(source: OGCRecordResponse) {
    setSelectedSources((prev) => [...prev, source]);
    setSearchQuery('');
    setIsDropdownOpen(false);
    searchInputRef.current?.focus();
  }

  function handleRemoveSource(id: string) {
    setSelectedSources((prev) => prev.filter((s) => s.id !== id));
  }

  async function handleSubmit() {
    if (isSubmitDisabled) return;

    try {
      const result = await createVrtMutation.mutateAsync({
        source_dataset_ids: selectedSources.map((s) => s.id),
        vrt_type: vrtType,
        resolution_strategy: resolutionStrategy,
        title: title.trim(),
        summary: summary.trim() || null,
        visibility: 'private',
      });
      setJobId(String(result.job_id));
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : t('vrt.submitFailed');
      toast.error(message);
    }
  }

  if (jobId) {
    return (
      <JobProgress
        jobId={jobId}
        onReset={() => {
          setJobId(null);
          resetForm();
        }}
      />
    );
  }

  const firstSource = selectedSources[0];

  return (
    <TooltipProvider>
      <div className="space-y-6 max-w-2xl">
        {/* Mode Selector */}
        <div className="space-y-2">
          <ToggleGroup
            type="single"
            value={vrtType}
            onValueChange={(val) => {
              if (val) setVrtType(val as VrtType);
            }}
          >
            <ToggleGroupItem value="mosaic">{t('vrt.modeMosaic')}</ToggleGroupItem>
            <ToggleGroupItem value="band_stack">{t('vrt.modeBandStack')}</ToggleGroupItem>
          </ToggleGroup>
          <p className="text-sm text-muted-foreground">
            {vrtType === 'mosaic' ? t('vrt.mosaicHelp') : t('vrt.bandStackHelp')}
          </p>
        </div>

        {/* Resolution Strategy (mosaic only) */}
        {vrtType === 'mosaic' && (
          <div className="space-y-1.5">
            <Label>{t('vrt.resolutionStrategy')}</Label>
            <Select
              value={resolutionStrategy}
              onValueChange={(val) => setResolutionStrategy(val as ResolutionStrategy)}
            >
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="finest">{t('vrt.resFinest')}</SelectItem>
                <SelectItem value="coarsest">{t('vrt.resCoarsest')}</SelectItem>
                <SelectItem value="average">{t('vrt.resAverage')}</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-sm text-muted-foreground">
              {resolutionStrategy === 'finest' && t('vrt.resFinestHelp')}
              {resolutionStrategy === 'coarsest' && t('vrt.resCoarsestHelp')}
              {resolutionStrategy === 'average' && t('vrt.resAverageHelp')}
            </p>
          </div>
        )}

        {/* COG Search Picker */}
        <div className="space-y-2">
          <Label>{t('vrt.searchLabel')}</Label>
          <div className="relative" ref={dropdownRef}>
            <div className="relative">
              <Search className="absolute start-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                ref={searchInputRef}
                className="ps-8 pe-8"
                placeholder={t('vrt.searchPlaceholder')}
                value={searchQuery}
                disabled={selectedSources.length >= VRT_MAX_SOURCES}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setIsDropdownOpen(true);
                }}
                onFocus={() => {
                  if (debouncedQuery.length >= 2) setIsDropdownOpen(true);
                }}
                onBlur={() => {
                  // Delay to allow click on dropdown items
                  setTimeout(() => setIsDropdownOpen(false), 150);
                }}
              />
              {isSearchFetching && (
                <Loader2 className="absolute end-2.5 top-2.5 h-4 w-4 animate-spin text-muted-foreground" />
              )}
            </div>

            {/* Search results dropdown */}
            {isDropdownOpen && debouncedQuery.length >= 2 && (
              <Card className="absolute z-50 w-full mt-1 shadow-lg">
                <CardContent className="p-0">
                  {searchError && (
                    <p className="text-sm text-destructive px-3 py-2">{t('vrt.searchError', { defaultValue: 'Failed to load results' })}</p>
                  )}
                  {!searchError && filteredResults.length === 0 ? (
                    <p className="px-3 py-2 text-sm text-muted-foreground">
                      {t('vrt.noResults')}
                    </p>
                  ) : (
                    <ul className="max-h-60 overflow-auto divide-y">
                      {filteredResults.map((result) => (
                        <li key={result.id}>
                          <button
                            type="button"
                            className="w-full text-start px-3 py-2 hover:bg-muted/50 transition-colors"
                            onClick={() => handleAddSource(result)}
                          >
                            <div className="font-medium text-sm">{result.properties.title}</div>
                            <div className="text-xs text-muted-foreground flex gap-3 mt-0.5">
                              {result.properties.crs && (
                                <span>{result.properties.crs}</span>
                              )}
                              {result.properties.band_count != null && (
                                <span>{result.properties.band_count} band{result.properties.band_count !== 1 ? 's' : ''}</span>
                              )}
                              {result.properties.res_x != null && (
                                <span>res: {result.properties.res_x.toFixed(4)}</span>
                              )}
                            </div>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            )}
          </div>

          {/* Source count */}
          <p className="text-xs text-muted-foreground">
            {t('vrt.sourceCount', { count: selectedSources.length, max: VRT_MAX_SOURCES })}
          </p>

          {/* Selected sources list */}
          {selectedSources.length > 0 && (
            <ul className="space-y-2">
              {selectedSources.map((source, index) => {
                const errs = validationErrors[source.id] ?? [];
                const hasSourceErrors = errs.length > 0;
                return (
                  <li
                    key={source.id}
                    className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${hasSourceErrors ? 'border-destructive' : ''}`}
                  >
                    <span className="font-mono text-xs text-muted-foreground w-5 shrink-0">
                      {index + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium truncate">{source.properties.title}</div>
                      <div className="text-xs text-muted-foreground flex gap-2 mt-0.5">
                        {source.properties.crs && (
                          <Badge variant="outline" className="text-xs py-0 h-4">
                            {source.properties.crs}
                          </Badge>
                        )}
                        {source.properties.band_count != null && (
                          <span>{source.properties.band_count} band{source.properties.band_count !== 1 ? 's' : ''}</span>
                        )}
                      </div>
                    </div>
                    {hasSourceErrors && firstSource && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
                        </TooltipTrigger>
                        <TooltipContent>
                          <ul className="text-xs space-y-0.5">
                            {errs.map((code) => (
                              <li key={code}>{errorMessage(code, source, firstSource, t)}</li>
                            ))}
                          </ul>
                        </TooltipContent>
                      </Tooltip>
                    )}
                    <button
                      type="button"
                      onClick={() => handleRemoveSource(source.id)}
                      className="text-muted-foreground hover:text-foreground shrink-0"
                      aria-label={t('vrt.removeSource', { title: source.properties.title })}
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          {selectedSources.length < 2 && (
            <p className="text-xs text-muted-foreground">{t('vrt.minSources')}</p>
          )}
        </div>

        {/* Title */}
        <div className="space-y-1.5">
          <Label htmlFor="vrt-title">{t('vrt.titleLabel')}</Label>
          <Input
            id="vrt-title"
            placeholder={t('vrt.titlePlaceholder')}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>

        {/* Summary */}
        <div className="space-y-1.5">
          <Label htmlFor="vrt-summary">{t('vrt.summaryLabel')}</Label>
          <textarea
            id="vrt-summary"
            className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            placeholder={t('vrt.summaryPlaceholder')}
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
          />
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-2">
          {onCancel && (
            <Button type="button" variant="outline" onClick={onCancel}>
              {t('common:cancel')}
            </Button>
          )}
          <Button onClick={handleSubmit} disabled={isSubmitDisabled}>
            {createVrtMutation.isPending ? (
              <>
                <Loader2 className="me-2 h-4 w-4 animate-spin" />
                {t('vrt.submitting')}
              </>
            ) : (
              t('vrt.submit')
            )}
          </Button>
        </div>
      </div>
    </TooltipProvider>
  );
}
