import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { DatasetResponse } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { formatDate, formatBytes, formatRelativeDate, formatResolution, formatNodata } from '@/lib/format';
import { resolveProvenanceIdentity, formatProvenanceTime } from '@/lib/provenance-attribution';
import {
  ChevronDown,
  Copy,
  Check,
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

// Syntax highlight tokens — matches design mockup color scheme
const SYN = {
  kw:  'text-[oklch(0.75_0.17_300)]',   // keywords — purple
  fn:  'text-[oklch(0.78_0.13_220)]',   // functions — blue
  str: 'text-[oklch(0.78_0.13_140)]',   // strings — green
  num: 'text-[oklch(0.8_0.14_70)]',     // numbers — orange
  com: 'text-[oklch(0.5_0.008_250)] italic', // comments — gray
} as const;

/** API access code snippet with copy button */
function ApiSnippet({ dataset }: { dataset: DatasetResponse }) {
  const { t } = useTranslation('dataset');
  const [activeTab, setActiveTab] = useState<'curl' | 'python' | 'qgis'>('curl');
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  const baseUrl = window.location.origin;
  const collectionId = dataset.table_name;
  const srid = dataset.srid ?? 4326;

  const plainText: Record<string, string> = {
    curl: `# Fetch the first 10 features as GeoJSON\ncurl "${baseUrl}/api/v1/collections/${collectionId}/items?limit=10"`,
    python: `import geopandas as gpd\n\ngdf = gpd.read_file(\n    "${baseUrl}/api/v1/collections/${collectionId}/items"\n)\ngdf.head()`,
    qgis: `# In QGIS: Browser panel → WFS / OGC API → New Connection\n\nURL:        ${baseUrl}/api/v1\nCollection: ${collectionId}\nCRS:        EPSG:${srid}`,
  };

  const highlighted: Record<string, React.ReactNode> = {
    curl: (
      <>
        <span className={SYN.com}>{'# Fetch the first 10 features as GeoJSON'}</span>{'\n'}
        curl <span className={SYN.str}>{`"${baseUrl}/api/v1/collections/${collectionId}/items?limit=`}</span><span className={SYN.num}>10</span><span className={SYN.str}>"</span>
      </>
    ),
    python: (
      <>
        <span className={SYN.kw}>import</span> geopandas <span className={SYN.kw}>as</span> gpd{'\n\n'}
        gdf = gpd.<span className={SYN.fn}>read_file</span>({'\n'}
        {'    '}<span className={SYN.str}>{`"${baseUrl}/api/v1/collections/${collectionId}/items"`}</span>{'\n'}
        ){'\n'}
        gdf.<span className={SYN.fn}>head</span>()
      </>
    ),
    qgis: (
      <>
        <span className={SYN.com}>{'# In QGIS: Browser panel → WFS / OGC API → New Connection'}</span>{'\n\n'}
        URL:        <span className={SYN.str}>{baseUrl}/api/v1</span>{'\n'}
        Collection: <span className={SYN.str}>{collectionId}</span>{'\n'}
        CRS:        <span className={SYN.str}>EPSG:{srid}</span>
      </>
    ),
  };

  async function handleCopy() {
    try { await navigator.clipboard.writeText(plainText[activeTab]); } catch { /* noop */ }
    setCopied(true);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 2000);
  }

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-[15px] font-semibold tracking-tight">
          {t('overview.apiTitle', { defaultValue: 'Access via API' })}
        </h2>
        <span className="font-mono text-[11px] text-muted-foreground tracking-wide">
          OGC API Features
        </span>
      </div>
      <div className="flex items-center gap-1 mb-3 bg-muted/40 border rounded-lg p-1 w-fit">
        {(['curl', 'python', 'qgis'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-3 py-1.5 font-mono text-[11.5px] font-medium rounded-md border-0 cursor-pointer',
              activeTab === tab
                ? 'bg-background text-foreground shadow-sm'
                : 'bg-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="rounded-lg overflow-hidden border bg-[oklch(0.17_0.006_250)] text-[oklch(0.92_0_0)]">
        <div className="flex items-center gap-2 px-3.5 py-2 bg-[oklch(0.14_0.006_250)] border-b border-[oklch(0.22_0.008_250)]">
          <span className="px-1.5 py-0.5 rounded font-mono text-[11px] font-semibold text-[oklch(0.75_0.14_155)] bg-[oklch(0.75_0.14_155_/_15%)]">
            {activeTab === 'qgis' ? 'ADD' : 'GET'}
          </span>
          <span className="font-mono text-[11px] text-[oklch(0.55_0_0)]">
            {activeTab === 'qgis' ? 'Layer → Add Vector Layer' : `${baseUrl}/api/v1/collections/${collectionId}/items`}
          </span>
          <span className="flex-1" />
          <button
            onClick={handleCopy}
            className="px-2 py-0.5 rounded text-[11px] font-mono bg-[oklch(0.22_0.008_250)] text-[oklch(0.8_0_0)] hover:text-white cursor-pointer border-0"
          >
            {copied ? <Check className="inline size-3 me-1" /> : <Copy className="inline size-3 me-1" />}
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
        <pre className="px-5 py-4 font-mono text-[12.5px] leading-7 overflow-x-auto whitespace-pre-wrap m-0">
          {highlighted[activeTab]}
        </pre>
      </div>
    </section>
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
            <SideKV label={t('metadata.updated', { defaultValue: 'Updated' })} value={formatRelativeDate(dataset.updated_at)} mono />
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
            {dataset.srid && (
              <SideKV label={t('overview.srid', { defaultValue: 'SRID' })} value={`${dataset.srid} (WGS 84)`} mono />
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

          {/* Schema summary */}
          {dataset.column_info && dataset.column_info.length > 0 && (
            <section>
              <div className="flex items-baseline justify-between mb-3">
                <h2 className="text-[15px] font-semibold tracking-tight">
                  {t('overview.schemaTitle', { defaultValue: 'Schema' })}
                </h2>
                <span className="font-mono text-[11px] text-muted-foreground tracking-wide">
                  {t('overview.schemaCount', { count: dataset.column_info.length, defaultValue: '{{count}} columns' })}
                </span>
              </div>
              <div className="border rounded-lg overflow-hidden">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="bg-muted/40">
                      <th className="text-left px-4 py-2.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.1em] text-muted-foreground border-b">
                        {t('overview.schemaColumn', { defaultValue: 'Column' })}
                      </th>
                      <th className="text-left px-4 py-2.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.1em] text-muted-foreground border-b">
                        {t('overview.schemaType', { defaultValue: 'Type' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {dataset.column_info.map((col, i) => (
                      <tr key={col.name} className={cn('hover:bg-muted/20', i < dataset.column_info!.length - 1 && 'border-b')}>
                        <td className="px-4 py-2.5">
                          <span className="font-mono font-medium">{col.name}</span>
                        </td>
                        <td className="px-4 py-2.5">
                          <span className="font-mono text-[11.5px] text-primary tracking-wide">{col.type}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* API access snippet */}
          <ApiSnippet dataset={dataset} />
        </div>

        {/* ── Sidebar ── */}
        {sidebar}
      </div>
    </>
  );
}
