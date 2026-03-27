import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { DatasetResponse } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { formatDate, formatNumber, formatBytes } from '@/lib/format';
import { resolveProvenanceIdentity, formatProvenanceTime } from '@/lib/provenance-attribution';
import {
  Layers,
  Database,
  Calendar,
  ChevronDown,
  FileText,
  UserRound,
  AlertCircle,
  CheckCircle2,
} from 'lucide-react';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { DatasetCollectionBadges } from '@/components/collections/DatasetCollectionBadges';
import { AiAssistButton, AiDraftPreview } from '@/components/dataset/AiAssistButton';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { useSummaryDraft } from '@/hooks/use-ai-metadata';
import { useValidation } from '@/hooks/use-dataset';
import { useAuthStore } from '@/stores/auth-store';
import { useVrtGenerations } from '@/hooks/use-vrt';
import { InlineEdit } from '@/components/dataset/InlineEdit';
import { EditableFieldShell } from '@/components/dataset/EditableFieldShell';
import { SectionCapabilityHint } from '@/components/dataset/SectionCapabilityHint';
import { MetadataField } from '@/components/dataset/MetadataField';
import { RelatedDatasets } from '@/components/dataset/RelatedDatasets';
import { UsedInMaps } from '@/components/dataset/UsedInMaps';
import type { DatasetEditCapabilities } from '@/hooks/use-dataset-edit-capabilities';
import { getGeometryTypeLabel, getRecordStatusLabel, getSourceFormatLabel } from '@/i18n/labels';


interface OverviewTabProps {
  dataset: DatasetResponse;
  canEdit: boolean;
  capabilities: DatasetEditCapabilities;
  summaryValue: string;
  onSummaryDraftSave: (value: string) => void;
  onSummaryDirtyChange: (isDirty: boolean) => void;
  datasetId?: string;
  onNavigateToValidationField?: (field: string) => void;
}

export function OverviewTab({
  dataset,
  canEdit,
  capabilities,
  summaryValue,
  onSummaryDraftSave,
  onSummaryDirtyChange,
  datasetId,
  onNavigateToValidationField,
}: OverviewTabProps) {
  const { t, i18n } = useTranslation('dataset');

  const unknownLabel = t('metadata.provenanceUnknown', { defaultValue: 'Unknown' });
  const restrictedLabel = t('metadata.provenanceRestricted', { defaultValue: 'Restricted user' });
  const systemLabel = t('metadata.provenanceSystem', { defaultValue: 'System' });
  const neverLabel = t('metadata.never', { defaultValue: 'Never' });
  const notAvailableLabel = t('common:notAvailable', { defaultValue: 'Not available' });

  const createdByIdentity = resolveProvenanceIdentity(dataset.created_by_display, {
    unknown: unknownLabel,
    restricted: restrictedLabel,
    system: systemLabel,
  });
  const createdTime = formatProvenanceTime(dataset.created_at, {
    fallbackRelative: notAvailableLabel,
    fallbackAbsolute: notAvailableLabel,
    locale: i18n.language,
  });

  const lastEditedHasTimestamp = Boolean(dataset.last_edited_at);
  const lastEditedIdentity = lastEditedHasTimestamp
    ? resolveProvenanceIdentity(dataset.last_edited_by_display, {
        unknown: unknownLabel,
        restricted: restrictedLabel,
        system: systemLabel,
      })
    : neverLabel;
  const lastEditedTime = formatProvenanceTime(
    lastEditedHasTimestamp ? dataset.last_edited_at : null,
    {
      fallbackRelative: neverLabel,
      fallbackAbsolute: neverLabel,
      locale: i18n.language,
    },
  );

  const { isAIAvailable } = useAIAvailability();
  const summaryDraft = useSummaryDraft();
  const [summaryDraftText, setSummaryDraftText] = useState<string | null>(null);
  const [summaryExpanded, setSummaryExpanded] = useState(false);

  const isRaster = dataset.record_type === 'raster_dataset';
  const isVrt = dataset.record_type === 'vrt_dataset';

  // Health / QA block (skip for anonymous users — endpoint requires auth)
  const token = useAuthStore((s) => s.token);
  const resolvedDatasetId = datasetId ?? dataset.id;
  const { data: validationData } = useValidation(token ? resolvedDatasetId : undefined);
  const requiredCount = validationData?.errors?.length ?? 0;
  const recommendedCount = validationData?.warnings?.length ?? 0;
  const totalValidatableFields = 12;
  const passedCount = Math.max(0, totalValidatableFields - requiredCount - recommendedCount);
  const completionPercent = totalValidatableFields > 0 ? Math.round((passedCount / totalValidatableFields) * 100) : 100;
  const hasIssues = requiredCount > 0 || recommendedCount > 0;

  // VRT derivation -- pass empty string for non-VRT so the hook's enabled:!!datasetId disables the query
  const { data: generationsData } = useVrtGenerations(isVrt ? dataset.id : '', { limit: 1 });
  const lastGeneration = generationsData?.generations?.[0];

  return (
    <>
      {/* Compact Health / QA Block */}
      {hasIssues ? (
        <div className="flex items-center gap-2 p-3 rounded-lg border bg-muted/30 text-sm">
          <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
          <span>
            {requiredCount > 0 && <span className="font-medium">{requiredCount} required</span>}
            {requiredCount > 0 && recommendedCount > 0 && ' · '}
            {recommendedCount > 0 && <span>{recommendedCount} recommended</span>}
            {' · '}
            <span>{completionPercent}% complete</span>
            {(() => {
              const nextField = validationData?.errors?.[0]?.field ?? validationData?.warnings?.[0]?.field;
              if (!nextField) return null;
              return (
                <>
                  {' · '}
                  <button
                    type="button"
                    className="text-primary underline underline-offset-2 hover:text-primary/80"
                    onClick={() => onNavigateToValidationField?.(nextField)}
                  >
                    Next: fill in {nextField}
                  </button>
                </>
              );
            })()}
          </span>
          <Button
            variant="outline"
            size="sm"
            className="ml-auto"
            onClick={() => onNavigateToValidationField?.('validation')}
          >
            Review issues
          </Button>
        </div>
      ) : validationData ? (
        <div className="flex items-center gap-2 p-3 rounded-lg border bg-muted/30 text-sm text-green-600 dark:text-green-400">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>All checks passed</span>
        </div>
      ) : null}

      {/* Identity */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {isVrt
              ? t('sections.identityAndDerivation', { defaultValue: 'Identity & Derivation' })
              : t('sections.identity')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {!isRaster && !isVrt && dataset.geometry_type && (
              <MetadataField icon={Layers} label={t('metadata.geometryType')}>
                <Badge variant="outline">{getGeometryTypeLabel(t, dataset.geometry_type)}</Badge>
              </MetadataField>
            )}

            {!isRaster && !isVrt && (
              <MetadataField icon={Database} label={dataset.record_type === 'table' ? t('metadata.rowCount', { defaultValue: 'Row Count' }) : t('metadata.featureCount')}>
                {formatNumber(dataset.feature_count)}
              </MetadataField>
            )}

            {!isVrt && (
              <MetadataField icon={FileText} label={t('metadata.sourceFormat')}>
                {dataset.source_format ? getSourceFormatLabel(t, dataset.source_format) : t('common:notAvailable')}
              </MetadataField>
            )}

            {isVrt && dataset.raster?.source_count != null && (
              <MetadataField icon={Layers} label={t('metadata.sourceCount', { defaultValue: 'Source Count' })}>
                {dataset.raster.source_count}
              </MetadataField>
            )}

            {isVrt && dataset.raster?.resolution_strategy && (
              <MetadataField label={t('metadata.resolutionStrategy', { defaultValue: 'Resolution Strategy' })}>
                <Badge variant="outline">{dataset.raster.resolution_strategy}</Badge>
              </MetadataField>
            )}

            {isVrt && dataset.raster?.vrt_type && (
              <MetadataField label={t('overview.vrtType', { defaultValue: 'VRT Type' })}>
                <Badge variant="outline">
                  {dataset.raster.vrt_type === 'band_stack' ? 'Band Stack' : 'Mosaic'}
                </Badge>
              </MetadataField>
            )}

            {isVrt && dataset.raster && (
              <MetadataField label={t('overview.generationStatus', { defaultValue: 'Status' })}>
                <Badge
                  variant="outline"
                  className={
                    dataset.raster.status === 'ready'
                      ? 'border-green-500 text-green-600 dark:text-green-400'
                      : dataset.raster.status === 'regenerating'
                        ? 'border-yellow-500 text-yellow-600 dark:text-yellow-400'
                        : dataset.raster.status === 'failed'
                          ? 'border-red-500 text-red-600 dark:text-red-400'
                          : ''
                  }
                >
                  {dataset.raster.status
                    ? dataset.raster.status.charAt(0).toUpperCase() + dataset.raster.status.slice(1)
                    : notAvailableLabel}
                </Badge>
              </MetadataField>
            )}

            {isVrt && (
              <MetadataField icon={Calendar} label={t('overview.lastRegenerated', { defaultValue: 'Last Regenerated' })}>
                {lastGeneration?.started_at ? formatDate(lastGeneration.started_at) : t('metadata.never', { defaultValue: 'Never' })}
              </MetadataField>
            )}

            <MetadataField icon={Calendar} label={t('metadata.created')}>
              {formatDate(dataset.created_at)}
            </MetadataField>

            <MetadataField icon={Calendar} label={t('metadata.lastUpdated')}>
              {formatDate(dataset.updated_at)}
            </MetadataField>

            <MetadataField label={t('metadata.recordStatus')}>
              {dataset.record_status ? (
                <Badge variant="outline">{getRecordStatusLabel(t, dataset.record_status)}</Badge>
              ) : (
                t('common:notAvailable')
              )}
            </MetadataField>

            <MetadataField icon={UserRound} label={t('metadata.createdBy')}>
              <span title={createdTime.absolute}>
                {createdByIdentity} ({createdTime.relative})
              </span>
            </MetadataField>

            <MetadataField icon={UserRound} label={t('metadata.lastEditedBy')}>
              {lastEditedHasTimestamp ? (
                <span title={lastEditedTime.absolute}>
                  {lastEditedIdentity} ({lastEditedTime.relative})
                </span>
              ) : (
                neverLabel
              )}
            </MetadataField>
          </dl>

          {/* Summary with AI Assist */}
          <div className="mt-4 space-y-2" data-field-anchor="summary">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-muted-foreground">{t('sections.summary')}</p>
              {canEdit && isAIAvailable && (
                <AiAssistButton
                  onClick={() =>
                    summaryDraft
                      .mutateAsync(dataset.id)
                      .then((r) => setSummaryDraftText(r.draft))
                      .catch(() => toast.error(t('ai.summaryFailed')))
                  }
                  isPending={summaryDraft.isPending}
                  label={t('ai.generateSummary', { defaultValue: 'Generate summary' })}
                />
              )}
            </div>

            <SectionCapabilityHint capability={capabilities.summary} />

            <div className="text-sm">
              {!summaryValue && capabilities.summary.editable && !summaryExpanded ? (
                <div className="space-y-1">
                  <p className="text-sm text-muted-foreground italic">
                    {t('inline.noSummaryYet', { defaultValue: 'No summary added yet.' })}
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setSummaryExpanded(true)}
                  >
                    {t('inline.addSummary', { defaultValue: 'Add summary' })}
                  </Button>
                </div>
              ) : (
                <EditableFieldShell capability={capabilities.summary} testId="editable-field-shell-summary">
                  <InlineEdit
                    value={summaryValue}
                    onSave={async (value) => onSummaryDraftSave(value)}
                    as="p"
                    multiline
                    canEdit={capabilities.summary.editable}
                    placeholder={t('inline.noDescription')}
                    className="text-sm"
                    onDirtyChange={onSummaryDirtyChange}
                  />
                </EditableFieldShell>
              )}
            </div>

            {summaryDraftText !== null && (
              <AiDraftPreview
                draft={summaryDraftText}
                onAccept={async (editedText) => {
                  onSummaryDraftSave(editedText);
                  setSummaryDraftText(null);
                  toast.success(
                    t('affordances.pending.summaryStaged', {
                      defaultValue: 'Summary added to pending edits.',
                    }),
                  );
                }}
                onDiscard={() => setSummaryDraftText(null)}
              />
            )}
          </div>
        </CardContent>
      </Card>

      {/* Raster Properties */}
      {(isRaster || isVrt) && dataset.raster && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t('overview.rasterProperties', { defaultValue: 'Raster Properties' })}
            </CardTitle>
          </CardHeader>
          <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div>
              <span className="text-muted-foreground">
                {t('overview.resolution', { defaultValue: 'Resolution' })}
              </span>
              <p className="font-medium">
                {dataset.raster.res_x?.toFixed(6)} x {dataset.raster.res_y?.toFixed(6)}
              </p>
            </div>
            <div>
              <span className="text-muted-foreground">
                {t('overview.crs', { defaultValue: 'CRS' })}
              </span>
              <p className="font-medium">
                {dataset.raster.epsg ? `EPSG:${dataset.raster.epsg}` : 'Unknown'}
              </p>
            </div>
            <div>
              <span className="text-muted-foreground">
                {t('overview.bands', { defaultValue: 'Bands' })}
              </span>
              <p className="font-medium">{dataset.raster.band_count ?? notAvailableLabel}</p>
            </div>
            <div>
              <span className="text-muted-foreground">
                {t('overview.nodata', { defaultValue: 'Nodata' })}
              </span>
              <p className="font-medium">{dataset.raster.nodata ?? 'None'}</p>
            </div>
            <div>
              <span className="text-muted-foreground">
                {t('overview.compression', { defaultValue: 'Compression' })}
              </span>
              <p className="font-medium">{dataset.raster.compression ?? notAvailableLabel}</p>
            </div>
            <div>
              <span className="text-muted-foreground">
                {t('overview.fileSize', { defaultValue: 'File Size' })}
              </span>
              <p className="font-medium">
                {dataset.raster.size_bytes ? formatBytes(dataset.raster.size_bytes) : notAvailableLabel}
              </p>
            </div>
            <div>
              <span className="text-muted-foreground">
                {t('overview.dimensions', { defaultValue: 'Dimensions' })}
              </span>
              <p className="font-medium">
                {dataset.raster.width} x {dataset.raster.height} px
              </p>
            </div>
          </div>

          {/* Band Details */}
          {dataset.raster.bands && dataset.raster.bands.length > 0 && (
            <div className="mt-4">
              <Collapsible defaultOpen={dataset.raster.bands.length <= 6}>
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="sm" className="w-full justify-between">
                    {t('overview.bandDetails', { defaultValue: 'Band Details' })}
                    <ChevronDown className="size-4" />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>#</TableHead>
                        <TableHead>{t('overview.bandType', { defaultValue: 'Type' })}</TableHead>
                        <TableHead>
                          {t('overview.bandNodata', { defaultValue: 'Nodata' })}
                        </TableHead>
                        <TableHead>
                          {t('overview.bandColor', { defaultValue: 'Color' })}
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {dataset.raster.bands.map((band) => (
                        <TableRow key={band.index}>
                          <TableCell>{band.index}</TableCell>
                          <TableCell>{band.dtype}</TableCell>
                          <TableCell>{band.nodata ?? notAvailableLabel}</TableCell>
                          <TableCell>{band.color_interp && band.color_interp !== 'undefined' ? band.color_interp : t('common:notSpecified', { defaultValue: 'Not specified' })}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CollapsibleContent>
              </Collapsible>
            </div>
          )}
          </CardContent>
        </Card>
      )}

      {/* Collections */}
      {dataset.collections && dataset.collections.length > 0 && (
        <Card>
          <CardContent className="pt-6">
            <DatasetCollectionBadges collections={dataset.collections} />
          </CardContent>
        </Card>
      )}

      {/* Related Datasets */}
      <RelatedDatasets datasetId={dataset.id} />

      {/* Used in Maps */}
      <UsedInMaps datasetId={dataset.id} />
    </>
  );
}
