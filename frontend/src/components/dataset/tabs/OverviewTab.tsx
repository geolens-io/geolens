import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { DatasetResponse } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { formatDate, formatBytes, formatResolution, formatNodata } from '@/lib/format';
import { resolveProvenanceIdentity } from '@/lib/provenance-attribution';
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
    <div className="grid grid-cols-[100px_1fr] gap-3 py-2 text-[12.5px] items-baseline">
      <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground pt-px">
        {label}
      </span>
      {children ?? (
        <span className={cn('font-medium truncate', mono && 'font-mono text-xs tracking-wide')} title={title ?? value}>
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
    <Card className="gap-2 py-4">
      <CardHeader className="pb-2">
        <CardTitle className="text-[11px] font-mono font-semibold uppercase tracking-[0.1em] text-foreground/70">
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
  const { t, i18n } = useTranslation('dataset');
  const { data, isLoading } = useDatasetVersions(datasetId);

  if (isLoading || !data || data.versions.length === 0) return null;

  const versions = [...data.versions].sort((a, b) => b.version_number - a.version_number).slice(0, 5);

  return (
    <Card className="gap-2 py-4">
      <CardHeader className="pb-2">
        <CardTitle className="text-[11px] font-mono font-semibold uppercase tracking-[0.1em] text-foreground/70">
          {t('overview.provenanceTitle')}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="relative ps-5">
          {/* Timeline line */}
          <div className="absolute left-[5px] top-2 bottom-2 w-px bg-border" />
          {versions.map((v, i) => (
            <div key={v.id} className={cn('relative pb-4 last:pb-0')}>
              {/* Timeline dot */}
              <div className={cn(
                'absolute -start-5 top-[5px] size-[9px] rounded-full border-[1.5px]',
                i === 0 ? 'border-primary bg-background' : 'border-muted-foreground/40 bg-muted',
              )} />
              <div className="font-mono text-[11px] text-muted-foreground tracking-wider uppercase mb-0.5">
                {formatDate(v.uploaded_at)}
                {' · '}v{v.version_number}
              </div>
              <div className="text-[13px] font-medium">
                {v.source_filename ?? t('overview.provenanceUpload')}
              </div>
              {v.feature_count != null && (
                <div className="text-[12px] text-muted-foreground mt-0.5">
                  {v.feature_count.toLocaleString(i18n.language)} {t('overview.provenanceFeatures')}
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
  /** Switch the active detail tab (e.g. from "View all data →" / "Edit in Metadata →"). */
  onTabChange?: (tab: string) => void;
}

export function OverviewTab({
  dataset,
  canEdit,
  capabilities,
  summaryValue,
  onSummaryDraftSave,
  onSummaryDirtyChange,
  onTabChange,
}: OverviewTabProps) {
  const { t } = useTranslation('dataset');

  const unknownLabel = t('metadata.provenanceUnknown', { defaultValue: 'Unknown' });
  const restrictedLabel = t('metadata.provenanceRestricted', { defaultValue: 'Restricted user' });
  const systemLabel = t('metadata.provenanceSystem', { defaultValue: 'System' });
  const notAvailableLabel = t('common:notAvailable', { defaultValue: 'Not available' });

  const createdByIdentity = resolveProvenanceIdentity(dataset.created_by_display, {
    unknown: unknownLabel,
    restricted: restrictedLabel,
    system: systemLabel,
  });

  const { isAIAvailable } = useAIAvailability();
  const summaryDraft = useSummaryDraft();
  const [summaryDraftText, setSummaryDraftText] = useState<string | null>(null);
  const [summaryExpanded, setSummaryExpanded] = useState(false);

  const isRaster = dataset.record_type === 'raster_dataset';
  const isVrt = dataset.record_type === 'vrt_dataset';

  // VRT derivation -- pass empty string for non-VRT so the hook's enabled:!!datasetId disables the query
  const { data: generationsData } = useVrtGenerations(isVrt ? dataset.id : '', { limit: 1 });
  const lastGeneration = generationsData?.generations?.[0];

  // ── Sidebar content (right rail) ──
  const sidebar = (
    <aside className="space-y-4">
      {/* Details card — catalog info at a glance. Named "Details" (not "Metadata")
          to avoid colliding with the full Metadata tab; bbox/CRS live in the stats
          strip + Metadata tab, so they're intentionally not repeated here. */}
      <Card className="gap-2 py-4">
        <CardHeader className="pb-2">
          <CardTitle className="text-[11px] font-mono font-semibold uppercase tracking-[0.1em] text-foreground/70">
            {t('overview.detailsTitle', { defaultValue: 'Details' })}
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="divide-y divide-border/60">
            {dataset.license && (
              <SideKV label={t('metadata.license', { defaultValue: 'License' })} value={dataset.license} />
            )}
            {dataset.source_organization && (
              <SideKV label={t('overview.source', { defaultValue: 'Source' })} value={dataset.source_organization} />
            )}
            {!isVrt && dataset.source_format && (
              <SideKV label={t('metadata.sourceFormat')} value={getSourceFormatLabel(t, dataset.source_format)} />
            )}
            {dataset.table_name && (
              <SideKV label={t('metadata.tableName', { defaultValue: 'Table' })} value={dataset.table_name} mono />
            )}
            <SideKV label={t('overview.maintainer', { defaultValue: 'Maintainer' })} value={createdByIdentity} />
            <SideKV label={t('overview.created', { defaultValue: 'Created' })} value={formatDate(dataset.created_at)} mono />
            {dataset.update_frequency && (
              <SideKV label={t('overview.cadence', { defaultValue: 'Cadence' })} value={dataset.update_frequency} />
            )}
          </div>
          {canEdit && onTabChange && (
            <button
              type="button"
              onClick={() => onTabChange('metadata')}
              className="mt-3 text-xs font-medium text-primary hover:underline"
            >
              {t('overview.editInMetadata', { defaultValue: 'Edit in Metadata →' })}
            </button>
          )}
        </CardContent>
      </Card>

      {/* Related datasets & where this is used — discovery content kept high in
          the rail so it isn't buried beneath metadata/tags/provenance */}
      <RelatedDatasets datasetId={dataset.id} />
      <UsedInMaps datasetId={dataset.id} />

      {/* VRT Derivation card — only for VRT datasets */}
      {isVrt && dataset.raster && (
        <Card className="gap-2 py-4">
          <CardHeader className="pb-2">
            <CardTitle className="text-[11px] font-mono font-semibold uppercase tracking-[0.1em] text-foreground/70">
              {t('sections.identityAndDerivation', { defaultValue: 'Derivation' })}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="divide-y divide-border/60">
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
        <Card className="gap-2 py-4">
          <CardHeader className="pb-2">
            <CardTitle className="text-[11px] font-mono font-semibold uppercase tracking-[0.1em] text-foreground/70">
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
                    initialEditing={summaryExpanded && !summaryValue}
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

          {/* Fields — compact schema glance for vector/table datasets so the main
              column carries content (mirrors Raster Properties below; the two
              branches are mutually exclusive by record type). */}
          {!isRaster && !isVrt && dataset.column_info && dataset.column_info.length > 0 && (
            <Card className="gap-2 py-4">
              <CardHeader>
                <CardTitle className="text-base">
                  {t('overview.fieldsTitle', { defaultValue: 'Fields' })}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-2 text-sm">
                  {dataset.column_info.slice(0, 12).map((col) => (
                    <div key={col.name} className="flex items-baseline justify-between gap-2 min-w-0">
                      <span className="font-medium truncate" title={col.name}>{col.name}</span>
                      <span className="font-mono text-xs text-muted-foreground shrink-0">{col.type}</span>
                    </div>
                  ))}
                </div>
                {onTabChange && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-3 -ms-2"
                    onClick={() => onTabChange('data')}
                  >
                    {t('overview.viewAllData', { defaultValue: 'View all data →' })}
                  </Button>
                )}
              </CardContent>
            </Card>
          )}

          {/* Raster Properties */}
          {(isRaster || isVrt) && dataset.raster && (
            <Card className="gap-2 py-4">
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
                          {dataset.raster.bands.map((band, i) => (
                            <TableRow key={i}>
                              <TableCell>{band.index || i + 1}</TableCell>
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
