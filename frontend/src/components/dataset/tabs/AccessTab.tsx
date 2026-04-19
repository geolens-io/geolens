import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { Copy, Check, Eye } from 'lucide-react';
import type { DatasetResponse } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { visibilityColors } from '@/lib/status-colors';
import { DistributionsList } from '@/components/dataset/DistributionsList';
import { ExportButton } from '@/components/dataset/ExportButton';
import { cn } from '@/lib/utils';

// Syntax highlight tokens for code snippets
const SYN = {
  kw:  'text-[oklch(0.75_0.17_300)]',
  fn:  'text-[oklch(0.78_0.13_220)]',
  str: 'text-[oklch(0.78_0.13_140)]',
  num: 'text-[oklch(0.8_0.14_70)]',
  com: 'text-[oklch(0.5_0.008_250)] italic',
} as const;

interface AccessTabProps {
  dataset: DatasetResponse;
  datasetId: string;
}

function TileUrlSection({ tileUrl }: { tileUrl: string }) {
  const { t } = useTranslation('dataset');
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(tileUrl);
    } catch {
      /* fallback */
    }
    setCopied(true);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 2000);
  }

  return (
    <Card className="mt-3">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">{t('distributions.tiles')}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-1.5">
          <Badge variant="outline" className="text-xs">XYZ</Badge>
          <div className="flex items-center gap-2">
            <code className="flex-1 rounded bg-muted px-2 py-1.5 font-mono text-xs text-foreground truncate" title={tileUrl}>
              {tileUrl}
            </code>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0"
              onClick={handleCopy}
              aria-label={t('distributions.copyUrl')}
              title={t('distributions.copyUrl')}
            >
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

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

export function AccessTab({ dataset, datasetId }: AccessTabProps) {
  const { t } = useTranslation('dataset');
  const isRaster = dataset.record_type === 'raster_dataset';
  const isVrt = dataset.record_type === 'vrt_dataset';

  return (
    <>
      {/* Distributions */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('distributions.title')}</CardTitle>
        </CardHeader>
        <CardContent>
          {dataset.record_id ? (
            <DistributionsList recordId={dataset.record_id} />
          ) : (
            <p className="text-sm text-muted-foreground">
              {t('distributions.noDistributions')}
            </p>
          )}
          {/* XYZ Tile URL for raster/VRT datasets */}
          {(isRaster || isVrt) && dataset.raster?.connect?.tile_url && (
            <TileUrlSection tileUrl={dataset.raster.connect.tile_url} />
          )}
          <p className="text-xs text-muted-foreground mt-4">
            {t('serviceUrls.authHelpSimple')}{' '}
            <Link to="/settings" className="underline hover:text-foreground">
              {t('serviceUrls.manageApiKeys')}
            </Link>
          </p>
        </CardContent>
      </Card>

      {/* API access snippet */}
      <ApiSnippet dataset={dataset} />

      {/* Export -- vector datasets only */}
      {!isRaster && !isVrt && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('page.export')}</CardTitle>
          </CardHeader>
          <CardContent>
            <ExportButton datasetId={datasetId} datasetName={dataset.title} recordType={dataset.record_type} />
          </CardContent>
        </Card>
      )}

      {/* Visibility */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-muted-foreground">
              {t('metadata.visibility')}:
            </span>
            <Badge
              className={
                visibilityColors[dataset.visibility] ??
                'bg-muted text-muted-foreground border-border'
              }
            >
              <Eye className="h-3 w-3 me-1" />
              {dataset.visibility}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            {t('metadataEdit.visibilityHelp')}
          </p>
        </CardContent>
      </Card>
    </>
  );
}
