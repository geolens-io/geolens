import { useTranslation } from 'react-i18next';
import { getBoundingVolumeLabel } from '@/i18n/labels';
import { formatBbox, formatBytes, formatNumber } from '@/lib/format';
import type { TilesetPreviewResponse } from '@/types/api';

/** What a staged 3D Tiles archive's preview found, as a label and value list. */
export function TilesetFacts({ preview }: { preview: TilesetPreviewResponse }) {
  const { t } = useTranslation('import');
  const facts: [string, string][] = [
    [t('detect.labels.version'), preview.version],
    [t('detect.labels.geometricError'), preview.geometric_error != null ? formatNumber(preview.geometric_error) : '—'],
    [t('detect.labels.volume'), getBoundingVolumeLabel(t, preview.bounding_volume)],
    [t('detect.labels.extent'), preview.extent_bbox ? formatBbox(preview.extent_bbox, '—') : t('detect.noExtent')],
    [t('detect.labels.unpacked'), formatBytes(preview.unpacked_bytes)],
    [t('detect.labels.entries'), formatNumber(preview.entry_count)],
  ];
  return (
    <>
      <h5 className="eyebrow mb-2">{t('detect.tilesetInfo')}</h5>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
        {facts.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="font-mono text-mini text-muted-foreground">{label}</dt>
            <dd className="font-mono text-mini">{value}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}
