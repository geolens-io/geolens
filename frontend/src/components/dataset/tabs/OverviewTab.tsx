import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { DatasetResponse } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { formatDate, formatBytes, formatResolution, formatNodata } from '@/lib/format';
import { resolveProvenanceIdentity, formatProvenanceTime } from '@/lib/provenance-attribution';
import { ChevronDown } from 'lucide-react';
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
import { useDatasetVersions } from '@/components/dataset/hooks/use-dataset';
import { useKeywords } from '@/components/dataset/hooks/use-records';
import { useVrtGenerations } from '@/components/import/hooks/use-vrt';
import { InlineEdit } from '@/components/dataset/InlineEdit';
import { EditableFieldShell } from '@/components/dataset/EditableFieldShell';
import { SectionCapabilityHint } from '@/components/dataset/SectionCapabilityHint';
import { RelatedDatasets } from '@/components/dataset/RelatedDatasets';
import { UsedInMaps } from '@/components/dataset/UsedInMaps';
import type { DatasetEditCapabilities } from '@/components/dataset/hooks/use-dataset-edit-capabilities';
import { getSourceFormatLabel } from '@/i18n/labels';
import { cn } from '@/lib/utils';
import { vrtRasterStatusColors } from '@/lib/status-colors';

/** Compact key-value row for sidebar cards — grid layout matching design */
function SideKV({ label, value, mono, title, children }: {
  label: string;
  value?: string;
  mono?: boolean;
  title?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-[100px_1fr] gap-3 py-2.5 text-[12.5px] items-baseline">
      <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted-foreground pt-px">
        {label}
      </span>
      {children ?? (
        <span className={cn('font-medium truncate', mono && 'font-mono text-xs tracking-wide')} title={title}>
          {value}
        </span>
      )}
    </div>
  );
}


/** Keywords/tags sidebar card */
function KeywordsSidebarCard({ recordId }: { recordId: string }) {
  const { t } = useTranslation('dataset');
  const { data, isLoading } = useKeywords(recordId);

  if (isLoading || !data || data.keywords.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-[10.5px] font-mono font-medium uppercase tracking-[0.12em] text-muted-foreground">
          {t('overview.tagsTitle', { defaultValue: 'Tags' })}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="flex flex-wrap gap-1.5">
          {data.keywords.map((kw) => (
            <span
              key={kw.id}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-muted border text-[11.5px] font-medium text-muted-foreground"
            >
              <span className="text-muted-foreground/60">#</span>
              {kw.keyword}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/** Provenance timeline sidebar card */
function ProvenanceTimeline({ datasetId }: { datasetId: string }) {
  const { t } = useTranslation('dataset');
  const { data, isLoading } = useDatasetVersions(datasetId);

  if (isLoading || !data || data.versions.length === 0) return null;

  const versions = [...data.versions].sort((a, b) => b.version_number - a.version_number).slice(0, 5);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-[10.5px] font-mono font-medium uppercase tracking-[0.12em] text-muted-foreground">
          {t('overview.provenanceTitle', { defaultValue: 'Provenance' })}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="relative pl-5">
          {/* Timeline line */}
          <div className="absolute left-[5px] top-2 bottom-2 w-px bg-border" />
          {versions.map((v, i) => (
            <div key={v.id} className={cn('relative pb-4 last:pb-0')}>
              {/* Timeline dot */}
              <div className={cn(
                'absolute -left-5 top-[5px] size-[9px] rounded-full border-[1.5px]',
                i === 0 ? 'border-primary bg-background' : 'border-muted-foreground/40 bg-muted',
              )} />
              <div className="font-mono text-[10.5px] text-muted-foreground tracking-wider uppercase mb-0.5">
                {formatDate(v.uploaded_at)}
                {' · '}v{v.version_number}
              </div>
              <div className="text-[13px] font-medium">
                {v.source_filename ?? t('overview.provenanceUpload', { defaultValue: 'Data upload' })}
              </div>
              {v.feature_count != null && (
                <div className="text-[12px] text-muted-foreground mt-0.5">
                  {v.feature_count.toLocaleString()} {t('overview.provenanceFeatures', { defaultValue: 'features' })}
                </div>
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

interface OverviewTabProps {
  dataset: DatasetResponse;
  canEdit: boolean;
  capabilities: DatasetEditCapabilities;
  summaryValue: string;
  onSummaryDraftSave: (value: string) => void;
  onSummaryDirtyChange: (isDirty: boolean) => void;
  datasetId?: string;
}

export function OverviewTab({
  dataset,
  canEdit,
  capabilities,
  summaryValue,
  onSummaryDraftSave,
  onSummaryDirtyChange,
  datasetId,
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

  // VRT derivation -- pass empty string for non-VRT so the hook's enabled:!!datasetId disables the query
  const { data: generationsData } = useVrtGenerations(isVrt ? dataset.id : '', { limit: 1 });
  const lastGeneration = generationsData?.generations?.[0];

  const bbox = dataset.extent_bbox && dataset.extent_bbox.length >= 4
    ? dataset.extent_bbox as [number, number, number, number]
    : null;

  // ── Sidebar content (right rail) ──
  const sidebar = (
    <aside className="space-y-4">
      {/* Metadata card — spatial & catalog info */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-[10.5px] font-mono font-medium uppercase tracking-[0.12em] text-muted-foreground">
            {t('overview.metadataTitle', { defaultValue: 'Metadata' })}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="divide-y divide-dashed divide-border">
            {dataset.license && (
              <SideKV label={t('metadata.license', { defaultValue: 'License' })} value={dataset.license} />
            )}
            {dataset.source_organization && (
              <SideKV label={t('overview.source', { defaultValue: 'Source' })} value={dataset.source_organization} />
            )}
            {!isVrt && dataset.source_format && (
              <SideKV label={t('metadata.sourceFormat')} value={getSourceFormatLabel(t, dataset.source_format)} />
            )}
            <SideKV label={t('overview.maintainer', { defaultValue: 'Maintainer' })} value={createdByIdentity} />
            <SideKV label={t('overview.created', { defaultValue: 'Created' })} value={formatDate(dataset.created_at)} mono />
            {dataset.update_frequency && (
              <SideKV label={t('overview.cadence', { defaultValue: 'Cadence' })} value={dataset.update_frequency} />
            )}
            {bbox && (
              <SideKV
                label={t('overview.bbox', { defaultValue: 'BBox' })}
                value={`${bbox[0].toFixed(2)}, ${bbox[1].toFixed(2)}, ${bbox[2].toFixed(2)}, ${bbox[3].toFixed(2)}`}
                mono
              />
            )}
          </div>
        </CardContent>
      </Card>

      {/* VRT Derivation card — only for VRT datasets */}
      {isVrt && dataset.raster && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-[10.5px] font-mono font-medium uppercase tracking-[0.12em] text-muted-foreground">
              {t('sections.identityAndDerivation', { defaultValue: 'Derivation' })}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="divide-y divide-dashed divide-border">
              {dataset.raster.source_count != null && (
                <SideKV label={t('metadata.sourceCount', { defaultValue: 'Sources' })} value={String(dataset.raster.source_count)} />
              )}
              {dataset.raster.resolution_strategy && (
                <SideKV label={t('metadata.resolutionStrategy', { defaultValue: 'Resolution' })} value={dataset.raster.resolution_strategy} />
              )}
              {dataset.raster.vrt_type && (
                <SideKV
                  label={t('overview.vrtType', { defaultValue: 'VRT Type' })}
                  value={dataset.raster.vrt_type === 'band_stack' ? t('overview.bandStack') : t('overview.mosaic')}
                />
              )}
              <SideKV label={t('overview.generationStatus', { defaultValue: 'Status' })}>
                <Badge
                  variant="outline"
                  className={dataset.raster.status ? (vrtRasterStatusColors[dataset.raster.status] ?? '') : ''}
                >
                  {dataset.raster.status
                    ? dataset.raster.status.charAt(0).toUpperCase() + dataset.raster.status.slice(1)
                    : notAvailableLabel}
                </Badge>
              </SideKV>
              <SideKV
                label={t('overview.lastRegenerated', { defaultValue: 'Last Regenerated' })}
                value={lastGeneration?.started_at ? formatDate(lastGeneration.started_at) : t('metadata.never', { defaultValue: 'Never' })}
                mono
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Collections */}
      {dataset.collections && dataset.collections.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-[10.5px] font-mono font-medium uppercase tracking-[0.12em] text-muted-foreground">
              {t('overview.appearsIn', { defaultValue: 'Appears in' })}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <DatasetCollectionBadges collections={dataset.collections} />
          </CardContent>
        </Card>
      )}

      {/* Tags / Keywords */}
      <KeywordsSidebarCard recordId={dataset.record_id} />

      {/* Related Datasets */}
      <RelatedDatasets datasetId={dataset.id} />

      {/* Used in Maps */}
      <UsedInMaps datasetId={dataset.id} />

      {/* Provenance timeline */}
      <ProvenanceTimeline datasetId={dataset.id} />
    </aside>
  );

  return (
    <>
      {/* Two-column layout: main content + sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-8">
        {/* ── Main column ── */}
        <div className="space-y-6 min-w-0">
          {/* About / Summary section */}
          <section>
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-[15px] font-semibold tracking-tight">
                {t('overview.aboutTitle', { defaultValue: 'About this dataset' })}
              </h2>
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

            <div className="text-sm leading-7 text-foreground" data-field-anchor="summary">
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
                    className="text-sm leading-7"
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
          </section>

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
                  <p className="font-medium font-mono">
                    {formatResolution(dataset.raster.res_x)} x {formatResolution(dataset.raster.res_y)}
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">
                    {t('overview.crs', { defaultValue: 'CRS' })}
                  </span>
                  <p className="font-medium font-mono">
                    {dataset.raster.epsg ? `EPSG:${dataset.raster.epsg}` : t('overview.unknown')}
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
                  <p className="font-medium font-mono text-xs" title={dataset.raster.nodata != null ? String(dataset.raster.nodata) : undefined}>{formatNodata(dataset.raster.nodata)}</p>
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
                              <TableCell title={band.nodata != null ? String(band.nodata) : undefined}>{formatNodata(band.nodata)}</TableCell>
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


        </div>

        {/* ── Sidebar ── */}
        {sidebar}
      </div>
    </>
  );
}
