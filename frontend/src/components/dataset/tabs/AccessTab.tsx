import { useState } from 'react';
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

interface AccessTabProps {
  dataset: DatasetResponse;
  datasetId: string;
}

function TileUrlSection({ tileUrl }: { tileUrl: string }) {
  const { t } = useTranslation('dataset');
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(tileUrl);
    } catch {
      /* fallback */
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
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
            <code className="flex-1 rounded bg-muted px-2 py-1.5 font-mono text-xs break-all text-foreground">
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

      {/* Export -- vector datasets only */}
      {!isRaster && !isVrt && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('page.export')}</CardTitle>
          </CardHeader>
          <CardContent>
            <ExportButton datasetId={datasetId} datasetName={dataset.title} />
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
              <Eye className="h-3 w-3 mr-1" />
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
