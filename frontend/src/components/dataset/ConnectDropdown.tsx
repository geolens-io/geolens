import { useTranslation } from 'react-i18next';
import { Copy, Link2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useDatasetAccessEndpoints } from '@/components/dataset/hooks/use-dataset-access';
import { useAuthStore } from '@/stores/auth-store';
import type { DatasetResponse } from '@/types/api';

interface ConnectDropdownProps {
  dataset: DatasetResponse;
}

async function copyToClipboard(value: string, t: (key: string, opts?: Record<string, unknown>) => string) {
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
  const preview = value.length > 60 ? `${value.slice(0, 60)}...` : value;
  toast.success(t('connect.copied', { preview }));
}

export function ConnectDropdown({ dataset }: ConnectDropdownProps) {
  const { t } = useTranslation('dataset');
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.roles?.includes('admin') ?? false;
  const { endpoints } = useDatasetAccessEndpoints(dataset);

  const isRaster = dataset.record_type === 'raster_dataset';
  const isVrt = dataset.record_type === 'vrt_dataset';
  const isTable = dataset.record_type === 'table';

  const cogUrl = dataset.raster?.connect?.download_url;
  const tileUrl = dataset.raster?.connect?.tile_url;
  const s3Uri = dataset.raster?.connect?.s3_uri;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <Link2 className="me-1 size-3.5" />
          {t('actions.connect', { defaultValue: 'Connect' })}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {isRaster && cogUrl && (
          <DropdownMenuItem
            onClick={() =>
              copyToClipboard(
                cogUrl.startsWith('http') ? cogUrl : `${window.location.origin}${cogUrl}`,
                t,
              )
            }
          >
            <Copy className="me-2 size-3.5" />
            {t('connect.copyCogUrl')}
          </DropdownMenuItem>
        )}
        {(isRaster || isVrt) && tileUrl && (
          <DropdownMenuItem onClick={() => copyToClipboard(tileUrl, t)}>
            <Copy className="me-2 size-3.5" />
            {t('connect.copyXyzTileUrl')}
          </DropdownMenuItem>
        )}
        {(isRaster || isVrt) && isAdmin && s3Uri && (
          <DropdownMenuItem onClick={() => copyToClipboard(s3Uri, t)}>
            <Copy className="me-2 size-3.5" />
            {t('connect.copyS3Uri')}
          </DropdownMenuItem>
        )}
        {!isRaster && !isVrt && (
          <>
            {endpoints.ogcFeaturesUrl && (
              <DropdownMenuItem
                onClick={() => copyToClipboard(endpoints.ogcFeaturesUrl!, t)}
              >
                <Copy className="me-2 size-3.5" />
                {t('connect.copyOgcFeaturesUrl', { defaultValue: 'Copy OGC Features URL' })}
              </DropdownMenuItem>
            )}
            {isTable && endpoints.csvExportUrl && (
              <DropdownMenuItem
                onClick={() => copyToClipboard(endpoints.csvExportUrl!, t)}
              >
                <Copy className="me-2 size-3.5" />
                {t('connect.copyCsvExportUrl', { defaultValue: 'Copy CSV Export URL' })}
              </DropdownMenuItem>
            )}
            {!isTable && endpoints.vectorTilesUrl && (
              <DropdownMenuItem
                onClick={() => copyToClipboard(endpoints.vectorTilesUrl!, t)}
              >
                <Copy className="me-2 size-3.5" />
                {t('connect.copyVectorTilesUrl', { defaultValue: 'Copy Vector Tiles URL' })}
              </DropdownMenuItem>
            )}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
