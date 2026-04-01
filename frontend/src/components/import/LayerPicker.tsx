import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ProbeResponse, LayerInfo } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { formatNumber } from '@/lib/format';

interface LayerPickerProps {
  probeResult: ProbeResponse;
  onSelect: (layer: LayerInfo) => void;
  onBack: () => void;
  error: string | null;
}

function findSelectedLayer(probeResult: ProbeResponse): LayerInfo | null {
  if (probeResult.selected_layer_id == null) return null;
  return (
    probeResult.layers.find(
      (l) =>
        l.layer_id === probeResult.selected_layer_id ||
        l.name === String(probeResult.selected_layer_id),
    ) ?? null
  );
}

export function LayerPicker({ probeResult, onSelect, onBack, error }: LayerPickerProps) {
  const { t } = useTranslation('import');
  const [selectedLayer, setSelectedLayer] = useState<LayerInfo | null>(() =>
    findSelectedLayer(probeResult),
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{t('layerPicker.title')}</CardTitle>
          <Badge variant="secondary">{probeResult.service_type}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}

        {probeResult.layers.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t('layerPicker.emptyState')}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('layerPicker.columnName')}</TableHead>
                  <TableHead>{t('layerPicker.columnGeometry')}</TableHead>
                  <TableHead>{t('layerPicker.columnFeatureCount')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {probeResult.layers.map((layer) => (
                  <TableRow
                    key={layer.name}
                    className={`cursor-pointer ${
                      selectedLayer?.name === layer.name ? 'bg-accent' : ''
                    }`}
                    onClick={() => setSelectedLayer(layer)}
                  >
                    <TableCell>{layer.title || layer.name}</TableCell>
                    <TableCell>
                      {layer.geometry_type ? getGeometryTypeLabel(t, layer.geometry_type) : '-'}
                    </TableCell>
                    <TableCell>
                      {layer.feature_count !== null
                        ? formatNumber(layer.feature_count)
                        : '-'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        <div className="flex justify-between">
          <Button variant="outline" onClick={onBack}>
            {t('common:back')}
          </Button>
          <Button
            disabled={selectedLayer === null}
            onClick={() => selectedLayer && onSelect(selectedLayer)}
          >
            {t('layerPicker.previewLayer')}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
