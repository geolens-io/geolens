import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { getBoundingVolumeLabel } from '@/i18n/labels';
import { formatBbox, formatBytes, formatNumber } from '@/lib/format';
import type { TilesetMetadata } from '@/types/api';

interface TilesetCardProps {
  tileset: TilesetMetadata;
  extentBbox: number[] | null;
}

/** A 3D Tiles dataset's tileset: its version, detail, volume, size, extent and contents. */
export function TilesetCard({ tileset, extentBbox }: TilesetCardProps) {
  const { t } = useTranslation('dataset');
  const notAvailable = t('common:notAvailable', { defaultValue: 'Not available' });
  const facts = [
    { label: t('tileset.version'), value: tileset.version ?? notAvailable },
    {
      label: t('tileset.geometricError'),
      value: tileset.geometric_error != null ? formatNumber(tileset.geometric_error) : notAvailable,
    },
    {
      label: t('tileset.boundingVolume'),
      value: tileset.bounding_volume ? getBoundingVolumeLabel(t, tileset.bounding_volume) : notAvailable,
    },
    { label: t('tileset.size'), value: formatBytes(tileset.size_bytes) },
  ];
  // Only a region carries geographic bounds; a box or sphere is in the tileset's own frame.
  const extent = tileset.bounding_volume === 'box' || tileset.bounding_volume === 'sphere'
    ? t('tileset.noExtent')
    : formatBbox(extentBbox, notAvailable);
  // Null for a tileset published before its contents were recorded, so the row is left out.
  const lists = [
    { label: t('tileset.contentTypes'), values: tileset.content_types },
    { label: t('tileset.extensionsRequired'), values: tileset.extensions_required },
  ].flatMap(({ label, values }) => (values ? [{ label, values }] : []));

  return (
    <Card density="compact">
      <CardHeader>
        <CardTitle level={2} className="text-base">{t('tileset.title')}</CardTitle>
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
            <dt className="text-muted-foreground">{t('tileset.extent')}</dt>
            <dd className="font-mono">{extent}</dd>
          </div>
          {lists.map(({ label, values }) => (
            <div key={label} className="col-span-full">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="font-mono break-words">
                {values.length ? values.join(', ') : t('common:none')}
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
