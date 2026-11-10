import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { Copy, Check } from 'lucide-react';
import { toast } from 'sonner';
import { useDatasetAccessEndpoints } from '@/components/dataset/hooks/use-dataset-access';
import { useDistributions } from '@/components/dataset/hooks/use-records';
import { useUpdateDataset } from '@/components/dataset/hooks/use-dataset';
import { usePermissions } from '@/hooks/use-permissions';
import { useCanSetPublicVisibility } from '@/hooks/use-settings';
import { listKeywords } from '@/api/records';
import type { DatasetResponse, DatasetVisibility } from '@/types/api';
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
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { formatMutationError } from '@/lib/error-map';
import { visibilityColors } from '@/lib/status-colors';
import { VisibilityIcon } from '@/components/maps/VisibilityIcon';
import { getVisibilityLabel } from '@/i18n/labels';
import { CopyButton } from '@/components/ui/copy-button';
import { URL_CHIP_CLASS } from '@/components/dataset/url-chip';
import { DistributionsList } from '@/components/dataset/DistributionsList';
import { TilesetAccess } from '@/components/dataset/TilesetAccess';
import { PointCloudAccess } from '@/components/dataset/PointCloudAccess';
import { DatasetWriteKeys } from '@/components/dataset/DatasetWriteKeys';
import { DatasetGroupShare } from '@/components/dataset/DatasetGroupShare';
import { recordTypeCapabilities } from '@/lib/record-types';
import { cn } from '@/lib/utils';

// Syntax highlight tokens — mapped to CSS custom properties in index.css
const SYN = {
  kw:  'text-(--code-keyword)',
  fn:  'text-(--code-function)',
  str: 'text-(--code-string)',
  num: 'text-(--code-number)',
  com: 'text-(--code-comment) italic',
} as const;

type SnippetTab = 'curl' | 'python' | 'qgis';

interface AccessTabProps {
  dataset: DatasetResponse;
  /** Owner-or-admin editor: mirrors the backend `check_dataset_write_access`.
   * Everyone else keeps the read-only visibility badge. */
  canEdit?: boolean;
  /** Owner or admin, whatever their role permits: who the dataset's key list
   * and revoke endpoints serve. Defaults to `canEdit`. */
  canManageKeys?: boolean;
}

/** The visibility values this control can move a dataset TO, in ladder order.
 * `restricted` is not one: it follows from sharing a private dataset with
 * groups (see DatasetGroupShare), and a non-admin owner who picked it directly
 * would lose access to their own dataset. A dataset already stored as
 * `restricted` still displays its own value (see below), a one-way exit, never
 * a silent coercion. The import pickers stay at private/public. */
const SELECTABLE_VISIBILITIES = ['private', 'internal', 'public'] as const;

/** The full ladder in widening order, for deciding whether a visibility move
 * ADDS readers. `restricted` sits between private and internal even though this
 * control cannot move TO it: a stored restricted dataset can still be moved
 * FROM it, and that move's direction matters. */
const VISIBILITY_LADDER = ['private', 'restricted', 'internal', 'public'] as const;

/** Copy text to clipboard with textarea fallback for non-HTTPS contexts. */
async function copyText(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const textarea = document.createElement('textarea');
    textarea.value = value;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
  }
}

function TileUrlSection({ tileUrl }: { tileUrl: string }) {
  const { t } = useTranslation('dataset');
  return (
    <section className="mt-4" aria-labelledby="distributions-xyz-tiles">
      <h3 id="distributions-xyz-tiles" className="mb-1 text-sm font-medium">{t('distributions.tiles')}</h3>
      <div className="py-2">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
          <Badge variant="outline" className="text-xs">XYZ</Badge>
          <div className="flex min-w-56 flex-1 basis-56 items-center gap-2">
            <code className={URL_CHIP_CLASS} title={tileUrl}>
              {tileUrl}
            </code>
            <CopyButton value={tileUrl} label={t('distributions.copyUrl')} />
          </div>
        </div>
      </div>
    </section>
  );
}

/** Build the curl URL with ?limit=10, safely handling relative URLs. */
function buildCurlUrl(ogcFeaturesUrl: string): string {
  try {
    const url = new URL(ogcFeaturesUrl);
    url.searchParams.set('limit', '10');
    return url.toString();
  } catch {
    const separator = ogcFeaturesUrl.includes('?') ? '&' : '?';
    return `${ogcFeaturesUrl}${separator}limit=10`;
  }
}

/** API access code snippet with copy button */
function ApiSnippet({
  apiBaseUrl,
  collectionId,
  ogcFeaturesUrl,
  srid,
}: {
  apiBaseUrl: string;
  collectionId: string;
  ogcFeaturesUrl: string;
  srid: number;
}) {
  const { t } = useTranslation('dataset');
  const [activeTab, setActiveTab] = useState<SnippetTab>('curl');
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  const curlUrl = buildCurlUrl(ogcFeaturesUrl);

  const plainText: Record<SnippetTab, string> = {
    curl: `# Fetch the first 10 features as GeoJSON\ncurl "${curlUrl}"`,
    python: `import geopandas as gpd\n\ngdf = gpd.read_file(\n    "${ogcFeaturesUrl}"\n)\ngdf.head()`,
    qgis: `# In QGIS: Browser panel → WFS / OGC API → New Connection\n\nURL:        ${apiBaseUrl}\nCollection: ${collectionId}\nCRS:        EPSG:${srid}`,
  };

  const highlighted: Record<SnippetTab, React.ReactNode> = {
    curl: (
      <>
        <span className={SYN.com}>{'# Fetch the first 10 features as GeoJSON'}</span>{'\n'}
        curl <span className={SYN.str}>{`"${curlUrl}"`}</span>
      </>
    ),
    python: (
      <>
        <span className={SYN.kw}>import</span> geopandas <span className={SYN.kw}>as</span> gpd{'\n\n'}
        gdf = gpd.<span className={SYN.fn}>read_file</span>({'\n'}
        {'    '}<span className={SYN.str}>{`"${ogcFeaturesUrl}"`}</span>{'\n'}
        ){'\n'}
        gdf.<span className={SYN.fn}>head</span>()
      </>
    ),
    qgis: (
      <>
        <span className={SYN.com}>{'# In QGIS: Browser panel → WFS / OGC API → New Connection'}</span>{'\n\n'}
        URL:        <span className={SYN.str}>{apiBaseUrl}</span>{'\n'}
        Collection: <span className={SYN.str}>{collectionId}</span>{'\n'}
        CRS:        <span className={SYN.str}>EPSG:{srid}</span>
      </>
    ),
  };

  async function handleCopy() {
    await copyText(plainText[activeTab]);
    setCopied(true);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 2000);
  }

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-base font-semibold tracking-tight">
          {t('distributions.connectWithClient')}
        </h2>
        <span className="font-mono text-mini text-muted-foreground tracking-wide">
          {t('overview.ogcApiFeatures', { defaultValue: 'OGC API Features' })}
        </span>
      </div>
      <div className="flex items-center gap-1 mb-3 bg-muted/40 border rounded-lg p-1 w-fit">
        {(['curl', 'python', 'qgis'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-3 py-1.5 font-mono text-xs font-medium rounded-md border-0 cursor-pointer',
              activeTab === tab
                ? 'bg-background text-foreground shadow-sm'
                : 'bg-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {tab === 'qgis' ? 'QGIS' : tab === 'python' ? 'Python' : 'curl'}
          </button>
        ))}
      </div>
      <div className="rounded-lg overflow-hidden border bg-(--code-bg) text-(--code-text)">
        <div className="flex items-center gap-2 px-3.5 py-2 bg-(--code-chrome) border-b border-(--code-chrome-border)">
          <span className="shrink-0 px-1.5 py-0.5 rounded-sm font-mono text-mini font-semibold text-(--code-method-badge) bg-(--code-method-badge-bg)">
            {activeTab === 'qgis' ? 'ADD' : 'GET'}
          </span>
          <span
            className="min-w-0 flex-1 truncate font-mono text-mini text-(--code-muted)"
            title={activeTab === 'qgis' ? undefined : ogcFeaturesUrl}
          >
            {activeTab === 'qgis' ? 'Layer → Add Vector Layer' : ogcFeaturesUrl}
          </span>
          <button
            onClick={handleCopy}
            className="shrink-0 px-2 py-0.5 rounded-sm text-mini font-mono bg-(--code-chrome-border) text-(--code-text)/80 hover:text-(--code-text) cursor-pointer border-0"
          >
            {copied ? <Check className="inline size-3 me-1" /> : <Copy className="inline size-3 me-1" />}
            {copied ? t('common:copied') : t('common:copy')}
          </button>
        </div>
        <pre className="px-5 py-4 font-mono text-xs leading-7 overflow-x-auto whitespace-pre-wrap m-0">
          {highlighted[activeTab]}
        </pre>
      </div>
    </section>
  );
}

export function AccessTab({ dataset, canEdit = false, canManageKeys = canEdit }: AccessTabProps) {
  const { t } = useTranslation('dataset');
  const { endpoints, publicApiBaseUrl } = useDatasetAccessEndpoints(dataset);
  const updateDataset = useUpdateDataset();
  // The restrict_public_visibility instance setting caps non-admins at
  // non-public; the server enforces it with a 403, this only disables the
  // affordance.
  const canSetPublic = useCanSetPublicVisibility();
  const canCreateKeys = usePermissions().can('edit_metadata');
  const isLegacyVisibility = !SELECTABLE_VISIBILITIES.includes(
    dataset.visibility as (typeof SELECTABLE_VISIBILITIES)[number],
  );

  // A visibility change held back while the owner confirms that keywords
  // inherited from the analysis source may reach readers who cannot open that
  // source.
  const [pendingChange, setPendingChange] = useState<{
    visibility: DatasetVisibility;
    keywords: string[];
  } | null>(null);
  // Probe sequence. Two quick selections leave both probes in flight, and
  // whichever resolved LAST wrote pendingChange, possibly for the earlier,
  // no-longer-intended value. Each invocation takes a fresh id; a response whose
  // id is no longer current is discarded.
  const probeSeq = useRef(0);
  // Going public is confirmed first, from any level, because anonymous readers
  // reach the data through the standards endpoints and downloads as well.
  const [confirmPublic, setConfirmPublic] = useState(false);

  function applyVisibility(visibility: DatasetVisibility) {
    updateDataset.mutate(
      { datasetId: dataset.id, data: { visibility } },
      {
        onSuccess: (result) => {
          toast.success(t('metadataEdit.visibilityUpdated'));
          // When the preflight probe failed, the PATCH response is the only
          // warning surface left; reading it makes "a failed probe never
          // blocks" a fallback instead of a hole.
          if (result?.metadata_warnings?.length) {
            toast.warning(result.metadata_warnings[0]);
          }
        },
        // Moving a dataset away from public while a public map uses it is a 422
        // from `_apply_visibility_change`. This control is the first UI that can
        // trigger it, so the message must reach the user rather than the select
        // silently snapping back.
        onError: (err) =>
          toast.error(formatMutationError('dataset:metadataEdit.visibilityFailed', err)),
      },
    );
  }

  function handleVisibilityChange(value: string) {
    if (value === dataset.visibility) return;
    if (value === 'public') {
      // Discards any earlier selection's probe still in flight.
      probeSeq.current++;
      setConfirmPublic(true);
      return;
    }
    void changeVisibility(value as DatasetVisibility);
  }

  async function changeVisibility(visibility: DatasetVisibility) {
    const seq = ++probeSeq.current;
    // Only a move that ADDS readers warrants the dialog. The probe asks an
    // absolute question ("does this audience exceed the source?"), so running
    // it on a narrowing move (public -> internal on an output already wider than
    // its source) would block the REMEDIATION behind a dialog claiming a wider
    // audience. An unknown stored value indexes to -1 and counts as widening;
    // over-warning is the safe direction.
    const widens =
      VISIBILITY_LADDER.indexOf(visibility as (typeof VISIBILITY_LADDER)[number]) >
      VISIBILITY_LADDER.indexOf(
        dataset.visibility as (typeof VISIBILITY_LADDER)[number],
      );
    if (widens) {
      // Ask the counterfactual ("at this visibility, would inherited keywords
      // reach someone who cannot open their source?") and put the diff in front
      // of the owner before the change applies. Advisory only: a failed probe
      // never blocks the change (the backend PATCH response still carries the
      // warning).
      try {
        const kw = await listKeywords(dataset.record_id, {
          audienceVisibility: visibility,
        });
        // Superseded by a newer selection while awaiting this response must
        // produce nothing, not even the fall-through.
        if (seq !== probeSeq.current) return;
        // The gap flag is authoritative (computed server-side over ALL keyword
        // rows); the fetched page only supplies display names. Keying the dialog
        // on the page's inherited entries let a page boundary skip the
        // confirmation.
        if (kw.inherited_audience_gap) {
          setPendingChange({
            visibility,
            keywords: kw.keywords.filter((k) => k.inherited).map((k) => k.keyword),
          });
          return;
        }
      } catch {
        // A superseded FAILED probe must not fire the direct PATCH for its stale
        // value either.
        if (seq !== probeSeq.current) return;
        // fall through to the plain mutate
      }
    }
    applyVisibility(visibility);
  }
  const { featureTable, tileToken } = recordTypeCapabilities(dataset.record_type);
  // 3D files have their own client URLs below; an empty list would only read as missing.
  const { data: distributionData } = useDistributions(dataset.record_id);
  const showDistributions =
    !['tiles3d_dataset', 'pointcloud_dataset'].includes(dataset.record_type) ||
    (distributionData?.distributions.length ?? 0) > 0;

  return (
    <>
      {/* Visibility */}
      <Card>
        <CardHeader>
          <CardTitle level={2} className="text-base">{t('distributions.accessPermissions')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-muted-foreground">
              {t('metadata.visibility')}:
            </span>
            {canEdit ? (
              <Select
                value={dataset.visibility}
                onValueChange={handleVisibilityChange}
                disabled={updateDataset.isPending}
              >
                <SelectTrigger
                  className="w-auto min-w-[160px]"
                  aria-label={t('metadataEdit.visibility')}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {/* A stored `restricted` dataset keeps showing what
                      it actually is — offered as the current value only, never
                      as a move. */}
                  {isLegacyVisibility && (
                    <SelectItem value={dataset.visibility} disabled>
                      {getVisibilityLabel(t, dataset.visibility)}
                    </SelectItem>
                  )}
                  {SELECTABLE_VISIBILITIES.map((value) => (
                    <SelectItem
                      key={value}
                      value={value}
                      disabled={value === 'public' && !canSetPublic}
                    >
                      {getVisibilityLabel(t, value)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Badge
                className={
                  visibilityColors[dataset.visibility] ??
                  'bg-muted text-muted-foreground border-border'
                }
              >
                <VisibilityIcon visibility={dataset.visibility} withLabel={false} />
                <span className="ms-1">{getVisibilityLabel(t, dataset.visibility)}</span>
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            {t('metadataEdit.visibilityHelp')}
          </p>
          {canEdit && !canSetPublic && (
            <p className="text-xs text-muted-foreground mt-1">
              {t('common:visibilityPublicAdminOnly')}
            </p>
          )}
          {/* The server sends the group list to the owner and admins only. */}
          {canEdit && dataset.groups && (
            <DatasetGroupShare
              datasetId={dataset.id}
              visibility={dataset.visibility}
              groups={dataset.groups}
            />
          )}
        </CardContent>
      </Card>

      {/* Downloads and service endpoints */}
      {showDistributions && (
        <Card>
          <CardHeader>
            <CardTitle level={2} className="text-base">{t('distributions.title')}</CardTitle>
          </CardHeader>
          <CardContent>
            {dataset.record_id ? (
              <DistributionsList
                recordId={dataset.record_id}
                canEdit={canEdit}
                visibility={dataset.visibility}
                datasetTitle={dataset.title}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                {t('distributions.noDistributions')}
              </p>
            )}
            {/* XYZ Tile URL for raster/VRT datasets */}
            {tileToken === 'raster' && dataset.raster?.connect?.tile_url && (
              <TileUrlSection tileUrl={dataset.raster.connect.tile_url} />
            )}
            {tileToken === 'vector' && dataset.record_type !== 'table' && dataset.visibility !== 'public' && (
              <p className="text-xs text-muted-foreground mt-4">{t('serviceUrls.vectorTilesKeyHint')}</p>
            )}
            <p className="text-xs text-muted-foreground mt-4">
              {t('serviceUrls.authHelpSimple')}{' '}
              <Link to="/settings" className="underline hover:text-foreground">
                {t('serviceUrls.manageApiKeys')}
              </Link>
            </p>
          </CardContent>
        </Card>
      )}

      {dataset.tileset && <TilesetAccess tileset={dataset.tileset} visibility={dataset.visibility} />}
      {dataset.pointcloud?.url && (
        <PointCloudAccess url={dataset.pointcloud.url} visibility={dataset.visibility} />
      )}

      {/* API access snippet */}
      {featureTable && endpoints.ogcFeaturesUrl && publicApiBaseUrl && (
        <ApiSnippet
          apiBaseUrl={publicApiBaseUrl}
          collectionId={dataset.id}
          ogcFeaturesUrl={endpoints.ogcFeaturesUrl}
          srid={dataset.srid ?? 4326}
        />
      )}

      {/* Anyone who may list and revoke the keys sees them; creating one also
          needs the edit_metadata capability and a geometry column, which every
          feature write requires. */}
      {canManageKeys && featureTable && (
        <DatasetWriteKeys
          datasetId={dataset.id}
          canCreate={canCreateKeys && dataset.geometry_type !== null}
        />
      )}

      <ConfirmDialog
        open={confirmPublic}
        onOpenChange={setConfirmPublic}
        title={t('metadataEdit.publicConfirmTitle')}
        description={t('metadataEdit.publicConfirmDescription')}
        confirm={{
          label: t('metadataEdit.publicConfirmAction'),
          onClick: () => {
            void changeVisibility('public');
          },
        }}
      />

      {/* The publish-moment diff — which inherited keywords the
          wider audience would see, with the option to back out and prune. */}
      <AlertDialog
        open={pendingChange !== null}
        onOpenChange={(open) => {
          if (!open) setPendingChange(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('keywords.inheritedConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('keywords.inheritedConfirmBody')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {/* The fetched page supplies display names only; a
              gap with no inherited names on the page still gets the dialog,
              with a generic line in place of the badges. */}
          {pendingChange && pendingChange.keywords.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {pendingChange.keywords.map((kw) => (
                <Badge key={kw} variant="secondary">
                  {kw}
                </Badge>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {t('keywords.inheritedGeneric')}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (pendingChange) applyVisibility(pendingChange.visibility);
                setPendingChange(null);
              }}
            >
              {t('keywords.inheritedConfirmContinue')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
