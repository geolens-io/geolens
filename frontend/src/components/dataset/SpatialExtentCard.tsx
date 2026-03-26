import { useTranslation } from 'react-i18next';
import { MapPin } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

function formatBbox(bbox: number[] | null, fallback: string): string {
  if (!bbox || bbox.length < 4) return fallback;
  return `(${bbox[0].toFixed(4)}, ${bbox[1].toFixed(4)}) to (${bbox[2].toFixed(4)}, ${bbox[3].toFixed(4)})`;
}

function formatSrid(
  srid: number | null,
  originalSrid: number | null,
  unknownLabel: string,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  const current = srid ? `EPSG:${srid}` : unknownLabel;
  if (originalSrid && originalSrid !== srid) {
    return `${current} (${t('metadata.original', { srid: originalSrid })})`;
  }
  return current;
}

interface SpatialExtentCardProps {
  extentBbox: number[] | null;
  srid: number | null;
  originalSrid: number | null;
}

export function SpatialExtentCard({ extentBbox, srid, originalSrid }: SpatialExtentCardProps) {
  const { t } = useTranslation('dataset');

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <MapPin className="h-4 w-4" />
          {t('metadata.spatialExtent')}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1">
          <span className="text-sm font-medium text-muted-foreground">{t('sections.boundingBox')}</span>
          <p className="text-sm font-mono">
            {formatBbox(extentBbox, t('page.noSpatialExtent'))}
          </p>
        </div>

        <div className="space-y-1">
          <span className="text-sm font-medium text-muted-foreground">{t('metadata.crsSrid')}</span>
          <p className="text-sm">
            {formatSrid(srid, originalSrid, t('metadata.unknown'), t)}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
