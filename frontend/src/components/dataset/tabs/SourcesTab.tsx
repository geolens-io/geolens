import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { Loader2, AlertCircle, Trash2, Search, Plus, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { useVrtSources, useAddVrtSource, useRemoveVrtSource, useVrtStatus, useVrtGenerations, useRegenerateVrt } from '@/hooks/use-vrt';
import { searchDatasets } from '@/api/search';
import { queryKeys } from '@/lib/query-keys';
import { ApiError } from '@/api/client';
import { Badge } from '@/components/ui/badge';
import { vrtGenerationColors } from '@/lib/status-colors';
import type { VrtSourceHealth } from '@/types/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { DatasetResponse } from '@/types/api';

interface SourcesTabProps {
  dataset: DatasetResponse;
  canEdit: boolean;
  datasetId: string;
}

export function SourcesTab({ dataset, canEdit, datasetId }: SourcesTabProps) {
  const { t } = useTranslation('dataset');

  const { data: sourcesData, isLoading } = useVrtSources(datasetId);
  const addVrtSource = useAddVrtSource(datasetId);
  const removeVrtSource = useRemoveVrtSource(datasetId);

  const sources = sourcesData?.sources ?? [];
  const status = dataset.raster?.status ?? null;
  const isRegenerating = status === 'regenerating';
  const isFailed = status === 'failed';
  const isDisabled = isRegenerating || isFailed;

  const { data: vrtStatus } = useVrtStatus(datasetId, isRegenerating);
  const { data: generationsData } = useVrtGenerations(datasetId);
  const regenerateMutation = useRegenerateVrt(datasetId);

  const healthMap = useMemo(() => {
    const map = new Map<string, VrtSourceHealth['status']>();
    vrtStatus?.source_health?.forEach(h => map.set(h.dataset_id, h.status));
    return map;
  }, [vrtStatus?.source_health]);

  const [showPicker, setShowPicker] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [removeTarget, setRemoveTarget] = useState<{ dataset_id: string; title: string } | null>(
    null,
  );

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const { data: searchResults, isFetching: isSearchFetching } = useQuery({
    queryKey: queryKeys.cogSearch.addSource(debouncedQuery),
    queryFn: () => searchDatasets({ q: debouncedQuery, record_type: 'raster_dataset', limit: '10' }),
    enabled: debouncedQuery.length >= 2,
  });

  const linkedIds = useMemo(() => new Set(sources.map((s) => s.dataset_id)), [sources]);

  const filteredResults = useMemo(() => {
    if (!searchResults) return [];
    return searchResults.features.filter((f) => !linkedIds.has(f.id));
  }, [searchResults, linkedIds]);

  async function handleAddSource(sourceDatasetId: string) {
    setShowPicker(false);
    setSearchQuery('');
    try {
      await addVrtSource.mutateAsync(sourceDatasetId);
      toast.success(t('vrt.addSourceSuccess', { defaultValue: 'Source added. VRT is regenerating.' }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.error(t('vrt.addSourceRegenerating', { defaultValue: 'VRT is currently regenerating. Try again shortly.' }));
      } else if (err instanceof ApiError && err.status === 422) {
        // Parse structured validation errors from the backend
        try {
          const parsed = JSON.parse(err.message);
          if (Array.isArray(parsed)) {
            const messages = parsed.map((e: { message?: string }) => e.message).filter(Boolean);
            toast.error(messages.join('; ') || err.message);
          } else {
            toast.error(err.message);
          }
        } catch {
          toast.error(err.message);
        }
      } else {
        const message = err instanceof ApiError ? err.message : String(err);
        toast.error(message);
      }
    }
  }

  async function handleRemoveConfirm() {
    if (!removeTarget) return;
    try {
      await removeVrtSource.mutateAsync(removeTarget.dataset_id);
      toast.success(t('vrt.removeSuccess', { defaultValue: 'Source removed. VRT is regenerating.' }));
      setRemoveTarget(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.error(t('vrt.addSourceRegenerating', { defaultValue: 'VRT is currently regenerating. Try again shortly.' }));
      } else {
        const message = err instanceof ApiError ? err.message : String(err);
        toast.error(message);
      }
    }
  }

  async function handleRegenerate() {
    try {
      await regenerateMutation.mutateAsync();
      toast.success(t('vrt.regenerateStarted', { defaultValue: 'VRT regeneration started.' }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.error(t('vrt.regenerateConflict', { defaultValue: 'VRT is already regenerating.' }));
      } else {
        toast.error(err instanceof ApiError ? err.message : String(err));
      }
    }
  }

  const vrtTypeBadge = dataset.raster?.vrt_type === 'band_stack'
    ? t('vrt.bandStack', { defaultValue: 'VRT Band Stack' })
    : t('vrt.mosaic', { defaultValue: 'VRT Mosaic' });

  return (
    <TooltipProvider>
      <div className="space-y-4">
        {/* Regeneration status banner */}
        {isRegenerating && (
          <div className="flex items-center gap-2 rounded-md border border-blue-300 bg-blue-50 px-4 py-3 text-sm text-blue-800 dark:border-blue-700 dark:bg-blue-950 dark:text-blue-200">
            <Loader2 className="h-4 w-4 animate-spin shrink-0" />
            <span>{t('vrt.regeneratingBanner', { defaultValue: 'VRT is regenerating. Source changes are disabled until complete.' })}</span>
          </div>
        )}
        {isFailed && (
          <div className="flex items-center gap-2 rounded-md border border-destructive bg-destructive/10 px-4 py-3 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{t('vrt.failedBanner', { defaultValue: 'VRT regeneration failed. Remove the problem source and try again.' })}</span>
          </div>
        )}
        {vrtStatus?.active_generation && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span>Elapsed: {Math.round(vrtStatus.active_generation.elapsed_seconds)}s</span>
          </div>
        )}

        {/* Header: source count, VRT type badge, add source */}
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">
              {t('vrt.sourceCount', { count: sources.length, defaultValue_one: '{{count}} source', defaultValue_other: '{{count}} sources' })}
            </span>
            {dataset.raster?.vrt_type && (
              <Badge variant="outline">{vrtTypeBadge}</Badge>
            )}
          </div>

          {canEdit && (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleRegenerate}
                disabled={isRegenerating || regenerateMutation.isPending}
              >
                <RefreshCw className={`mr-1 h-4 w-4 ${isRegenerating ? 'animate-spin' : ''}`} />
                {t('vrt.regenerate', { defaultValue: 'Regenerate' })}
              </Button>
              {isDisabled ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span>
                      <Button variant="outline" size="sm" disabled>
                        <Plus className="mr-1 h-4 w-4" />
                        {t('vrt.addSource', { defaultValue: 'Add Source' })}
                      </Button>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>
                    {t('vrt.disabledRegenerating', { defaultValue: 'Disabled while VRT is regenerating' })}
                  </TooltipContent>
                </Tooltip>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowPicker((prev) => !prev)}
                >
                  <Plus className="mr-1 h-4 w-4" />
                  {t('vrt.addSource', { defaultValue: 'Add Source' })}
                </Button>
              )}
            </div>
          )}
        </div>

        {/* Add-source inline picker */}
        {showPicker && (
          <div className="relative max-w-md">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-8 pr-8"
                placeholder={t('vrt.addSourcePlaceholder', { defaultValue: 'Search for a COG dataset...' })}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {isSearchFetching && (
                <Loader2 className="absolute right-2.5 top-2.5 h-4 w-4 animate-spin text-muted-foreground" />
              )}
            </div>
            {debouncedQuery.length >= 2 && (
              <Card className="absolute z-50 w-full mt-1 shadow-lg">
                <CardContent className="p-0">
                  {filteredResults.length === 0 ? (
                    <p className="px-3 py-2 text-sm text-muted-foreground">
                      {t('vrt.noResults', { defaultValue: 'No matching datasets found.' })}
                    </p>
                  ) : (
                    <ul className="max-h-60 overflow-auto divide-y">
                      {filteredResults.map((result) => (
                        <li key={result.id}>
                          <button
                            type="button"
                            className="w-full text-left px-3 py-2 hover:bg-muted/50 transition-colors"
                            onMouseDown={() => handleAddSource(result.id)}
                          >
                            <div className="font-medium text-sm">{result.properties.title}</div>
                            <div className="text-xs text-muted-foreground flex gap-3 mt-0.5">
                              {result.properties.crs && <span>{result.properties.crs}</span>}
                              {result.properties.band_count != null && (
                                <span>
                                  {result.properties.band_count} band
                                  {result.properties.band_count !== 1 ? 's' : ''}
                                </span>
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
        )}

        {/* Sources table */}
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead className="w-10">{t('vrt.sourceTablePos', { defaultValue: '#' })}</TableHead>
                <TableHead>{t('vrt.sourceTableTitle', { defaultValue: 'Dataset' })}</TableHead>
                <TableHead>{t('vrt.sourceTableCrs', { defaultValue: 'CRS' })}</TableHead>
                <TableHead>{t('vrt.sourceTableBands', { defaultValue: 'Bands' })}</TableHead>
                <TableHead>{t('vrt.sourceTableResolution', { defaultValue: 'Resolution' })}</TableHead>
                {canEdit && <TableHead className="w-12" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={canEdit ? 7 : 6}
                    className="text-center text-muted-foreground py-8"
                  >
                    No sources
                  </TableCell>
                </TableRow>
              ) : (
                sources.map((s) => (
                  <TableRow key={s.dataset_id}>
                    <TableCell className="w-8">
                      {healthMap.get(s.dataset_id) === 'healthy' ? (
                        <span className="inline-block h-2 w-2 rounded-full bg-green-500" title={t('vrt.healthHealthy', { defaultValue: 'Healthy' })} />
                      ) : healthMap.get(s.dataset_id) === 'missing' ? (
                        <Tooltip><TooltipTrigger asChild>
                          <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
                        </TooltipTrigger><TooltipContent>{t('vrt.healthMissing', { defaultValue: 'Source dataset deleted' })}</TooltipContent></Tooltip>
                      ) : healthMap.get(s.dataset_id) === 'inaccessible' ? (
                        <Tooltip><TooltipTrigger asChild>
                          <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
                        </TooltipTrigger><TooltipContent>{t('vrt.healthInaccessible', { defaultValue: 'Source file inaccessible' })}</TooltipContent></Tooltip>
                      ) : (
                        <span className="inline-block h-2 w-2 rounded-full bg-gray-300" />
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {s.position + 1}
                    </TableCell>
                    <TableCell>
                      <Link
                        to={`/datasets/${s.dataset_id}`}
                        className="text-primary hover:underline"
                      >
                        {s.title}
                      </Link>
                    </TableCell>
                    <TableCell>
                      {s.crs_epsg != null ? (
                        <Badge variant="outline" className="text-xs">
                          EPSG:{s.crs_epsg}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground text-xs">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {s.band_count != null ? (
                        <span className="text-sm">{s.band_count}</span>
                      ) : (
                        <span className="text-muted-foreground text-xs">—</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {s.resolution_x != null && s.resolution_y != null ? (
                        <span className="text-sm font-mono">
                          {s.resolution_x.toFixed(4)} × {s.resolution_y.toFixed(4)}
                        </span>
                      ) : (
                        <span className="text-muted-foreground text-xs">—</span>
                      )}
                    </TableCell>
                    {canEdit && (
                      <TableCell>
                        {isDisabled || sources.length <= 2 ? (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span>
                                <Button variant="ghost" size="icon" disabled aria-label={t('vrt.removeSource')}>
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </span>
                            </TooltipTrigger>
                            <TooltipContent>
                              {isDisabled
                                ? t('vrt.disabledRegenerating', { defaultValue: 'Disabled while VRT is regenerating' })
                                : t('vrt.disabledMinSources', { defaultValue: 'VRT must have at least 2 sources' })}
                            </TooltipContent>
                          </Tooltip>
                        ) : (
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => setRemoveTarget({ dataset_id: s.dataset_id, title: s.title })}
                            aria-label={t('vrt.removeSource')}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        )}
                      </TableCell>
                    )}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        )}

        {/* Generation History */}
        {generationsData && generationsData.generations.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-sm font-medium text-muted-foreground">
              {t('vrt.generationHistory', { defaultValue: 'Generation History' })}
            </h4>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-24">{t('vrt.genStatus', { defaultValue: 'Status' })}</TableHead>
                  <TableHead>{t('vrt.genTimestamp', { defaultValue: 'Timestamp' })}</TableHead>
                  <TableHead>{t('vrt.genDuration', { defaultValue: 'Duration' })}</TableHead>
                  <TableHead>{t('vrt.genSources', { defaultValue: 'Sources' })}</TableHead>
                  <TableHead>{t('vrt.genTriggeredBy', { defaultValue: 'Triggered By' })}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {generationsData.generations.map((gen) => (
                  <React.Fragment key={gen.id}>
                    <TableRow>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={vrtGenerationColors[gen.status] ?? ''}
                        >
                          {gen.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-sm">
                        {gen.started_at ? new Date(gen.started_at).toLocaleString() : '--'}
                      </TableCell>
                      <TableCell className="text-sm font-mono">
                        {gen.duration_seconds != null ? `${gen.duration_seconds.toFixed(1)}s` : '--'}
                      </TableCell>
                      <TableCell className="text-sm">{gen.source_count ?? '--'}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {gen.triggered_by === 'system' ? 'System' : gen.triggered_by ? 'User' : '--'}
                      </TableCell>
                    </TableRow>
                    {gen.status === 'failed' && gen.error_message && (
                      <TableRow>
                        <TableCell colSpan={5}>
                          <p className="text-xs text-destructive py-1">{gen.error_message}</p>
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* Remove confirmation dialog */}
      <AlertDialog open={!!removeTarget} onOpenChange={(open) => { if (!open) setRemoveTarget(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('vrt.removeConfirmTitle', { defaultValue: 'Remove Source' })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('vrt.removeConfirmBody', {
                title: removeTarget?.title ?? '',
                defaultValue: 'Remove "{{title}}" from this VRT? The VRT will regenerate.',
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel', { defaultValue: 'Cancel' })}</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleRemoveConfirm}
              variant="destructive"
            >
              {t('vrt.removeConfirmTitle', { defaultValue: 'Remove' })}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </TooltipProvider>
  );
}
