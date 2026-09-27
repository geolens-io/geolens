import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatBbox, formatBytes, formatNumber } from '@/lib/format';
import type { DatasetResponse } from '@/types/api';

/** File facts returned with a published COPC dataset. */
export function PointCloudCard({ dataset }: { dataset: DatasetResponse }) {
  const { t } = useTranslation('dataset');
  const pointcloud = dataset.pointcloud;
  if (!pointcloud) return null;

  const unavailable = t('common:notAvailable', { defaultValue: 'Not available' });
  const facts = [
    { label: t('pointcloud.pointCount'), value: formatNumber(pointcloud.point_count) },
    { label: t('pointcloud.crs'), value: dataset.srid ? `EPSG:${dataset.srid}` : unavailable },
    { label: t('pointcloud.size'), value: formatBytes(pointcloud.size_bytes) },
    {
      label: t('pointcloud.pointFormat'),
      value: pointcloud.point_format != null ? formatNumber(pointcloud.point_format) : unavailable,
    },
  ];

  return (
    <Card density="compact">
      <CardHeader>
        <CardTitle level={2} className="text-base">{t('pointcloud.title')}</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          {facts.map(({ label, value }) => (
            <div key={label}>
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="font-medium font-mono">{value}</dd>
            </div>
          ))}
          <div className="col-span-full">
            <dt className="text-muted-foreground">{t('pointcloud.bounds')}</dt>
            <dd className="font-mono">{formatBbox(dataset.extent_bbox, unavailable)}</dd>
          </div>
          {(dataset.z_min != null || dataset.z_max != null) && (
            <div className="col-span-full">
              <dt className="text-muted-foreground">{t('pointcloud.elevationRange')}</dt>
              <dd className="font-mono">
                {formatNumber(dataset.z_min)} – {formatNumber(dataset.z_max)}
              </dd>
            </div>
          )}
          {pointcloud.vertical_crs && (
            <div className="col-span-full">
              <dt className="text-muted-foreground">{t('pointcloud.verticalCrs')}</dt>
              <dd className="font-mono break-words">{pointcloud.vertical_crs}</dd>
            </div>
          )}
        </dl>
      </CardContent>
    </Card>
  );
}
