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
import { useAuthStore } from '@/stores/auth-store';
import type { DatasetResponse } from '@/types/api';

interface ConnectDropdownProps {
  dataset: DatasetResponse;
}

async function copyToClipboard(value: string, t: (key: string, opts?: Record<string, unknown>) => string) {
  await navigator.clipboard.writeText(value);
  const preview = value.length > 60 ? `${value.slice(0, 60)}...` : value;
  toast.success(t('connect.copied', { preview }));
}

export function ConnectDropdown({ dataset }: ConnectDropdownProps) {
  const { t } = useTranslation('dataset');
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.roles?.includes('admin') ?? false;

  const isRaster = dataset.record_type === 'raster_dataset';
  const isVrt = dataset.record_type === 'vrt_dataset';
  const isTable = dataset.record_type === 'table';

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <Link2 className="mr-1 size-3.5" />
          {t('actions.connect', { defaultValue: 'Connect' })}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {isRaster && dataset.raster?.connect?.download_url && (
          <DropdownMenuItem
            onClick={() =>
              copyToClipboard(
                dataset.raster!.connect!.download_url!.startsWith('http')
                  ? dataset.raster!.connect!.download_url!
                  : `${window.location.origin}${dataset.raster!.connect!.download_url!}`,
                t,
              )
            }
          >
            <Copy className="mr-2 size-3.5" />
            {t('connect.copyCogUrl')}
          </DropdownMenuItem>
        )}
        {(isRaster || isVrt) && dataset.raster?.connect?.tile_url && (
          <DropdownMenuItem
            onClick={() =>
              copyToClipboard(dataset.raster!.connect!.tile_url, t)
            }
          >
            <Copy className="mr-2 size-3.5" />
            {t('connect.copyXyzTileUrl')}
          </DropdownMenuItem>
        )}
        {(isRaster || isVrt) && isAdmin && dataset.raster?.connect?.s3_uri && (
          <DropdownMenuItem
            onClick={() => copyToClipboard(dataset.raster!.connect!.s3_uri!, t)}
          >
            <Copy className="mr-2 size-3.5" />
            {t('connect.copyS3Uri')}
          </DropdownMenuItem>
        )}
        {!isRaster && !isVrt && (
          <>
            <DropdownMenuItem
              onClick={() =>
                copyToClipboard(`${window.location.origin}/api/datasets/${dataset.id}`, t)
              }
            >
              <Copy className="mr-2 size-3.5" />
              {t('connect.copyApiUrl')}
            </DropdownMenuItem>
            {!isTable && (
              <DropdownMenuItem
                onClick={() =>
                  copyToClipboard(
                    `${window.location.origin}/tiles/data.${dataset.table_name}/{z}/{x}/{y}.pbf`,
                    t,
                  )
                }
              >
                <Copy className="mr-2 size-3.5" />
                {t('connect.copyTileUrl')}
              </DropdownMenuItem>
            )}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
