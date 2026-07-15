/* eslint-disable jsx-a11y/no-noninteractive-tabindex -- the named overflow region must be keyboard-scrollable */
import { RefreshCw, TableProperties } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import type { SharedLayerResponse } from '@/types/api';
import { createViewerLayerEntries } from '@/components/viewer/layer-identity';
import type { AccessibleMapFeatureResult } from './accessible-map-data';

interface AccessibleMapDataPanelProps {
  layers: SharedLayerResponse[];
  visibleLayers: Set<string>;
  featureResult: AccessibleMapFeatureResult;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRefresh: () => void;
  disabled?: boolean;
}

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatValue(
  value: unknown,
  locale: string,
  booleanTrue: string,
  booleanFalse: string,
): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? booleanTrue : booleanFalse;
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? value.toLocaleString(locale)
      : value.toLocaleString(locale, { maximumFractionDigits: 5 });
  }
  if (typeof value === 'object') return JSON.stringify(value) ?? '—';
  return String(value);
}

export function AccessibleMapDataPanel({
  layers,
  visibleLayers,
  featureResult,
  open,
  onOpenChange,
  onRefresh,
  disabled = false,
}: AccessibleMapDataPanelProps) {
  const { t, i18n } = useTranslation('common');
  const layerEntries = createViewerLayerEntries(layers);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          className="absolute bottom-20 left-3 z-30 bg-background/95 shadow-md backdrop-blur-sm"
        >
          <TableProperties aria-hidden="true" />
          {t('viewer.data.launch')}
        </Button>
      </SheetTrigger>
      <SheetContent
        side="bottom"
        className="max-h-[min(72vh,44rem)] gap-0 overflow-hidden p-0"
      >
        <SheetHeader className="border-b pe-12">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <SheetTitle>{t('viewer.data.title')}</SheetTitle>
              <SheetDescription>{t('viewer.data.description')}</SheetDescription>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={onRefresh}>
              <RefreshCw aria-hidden="true" />
              {t('viewer.data.refresh')}
            </Button>
          </div>
        </SheetHeader>

        {/* The panel is a real overflow region; make it keyboard-scrollable and
            give it a programmatic name for WCAG 2.1.1/2.4.3. */}
        <div
          className="min-h-0 overflow-y-auto p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
          tabIndex={0}
          role="region"
          aria-label={t('viewer.data.scrollLabel')}
        >
          <section aria-labelledby="map-data-layers-heading">
            <h3 id="map-data-layers-heading" className="text-sm font-semibold">
              {t('viewer.data.layersHeading')}
            </h3>
            <ul className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {layerEntries.map(({ layer, key }) => {
                const visible = visibleLayers.has(key);
                return (
                  <li key={key} className="rounded-md border bg-card p-3 text-sm">
                    <div className="flex items-start justify-between gap-3">
                      <span className="font-medium">
                        {layer.display_name || layer.dataset_name}
                      </span>
                      <span className={visible ? 'text-success' : 'text-muted-foreground'}>
                        {visible ? t('viewer.data.visible') : t('viewer.data.hidden')}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {layer.geometry_type ?? layer.dataset_record_type ?? layer.layer_type ?? '—'}
                      {' · '}
                      {layer.feature_count === null || layer.feature_count === undefined
                        ? t('viewer.data.featureCountUnknown')
                        : t('viewer.data.featureCount', { count: layer.feature_count })}
                    </p>
                  </li>
                );
              })}
            </ul>
          </section>

          <section className="mt-6" aria-labelledby="map-data-features-heading">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 id="map-data-features-heading" className="text-sm font-semibold">
                {t('viewer.data.featuresHeading')}
              </h3>
              <p className="text-xs text-muted-foreground" role="status" aria-live="polite">
                {featureResult.truncated
                  ? t('viewer.data.resultSummaryTruncated', {
                      shown: featureResult.features.length,
                      total: featureResult.total,
                    })
                  : t('viewer.data.resultSummary', { count: featureResult.total })}
              </p>
            </div>

            {featureResult.features.length === 0 ? (
              <p className="mt-3 rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                {t('viewer.data.noVisibleFeatures')}
              </p>
            ) : (
              <ol className="mt-3 space-y-3">
                {featureResult.features.map((feature, index) => {
                  const bounds = feature.bounds;
                  const isPoint = bounds
                    && bounds[0] === bounds[2]
                    && bounds[1] === bounds[3];
                  return (
                    <li key={feature.key}>
                      <article className="rounded-md border bg-card p-4">
                        <p className="text-xs font-medium text-muted-foreground">
                          {feature.layerName}
                        </p>
                        <h4 className="font-medium">
                          {feature.title || (feature.clusterCount
                            ? t('viewer.data.clusterLabel', { index: index + 1 })
                            : t('viewer.data.featureLabel', { index: index + 1 }))}
                        </h4>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {feature.clusterCount
                            ? t('viewer.data.clusterSummary', {
                                count: feature.clusterCount,
                              })
                            : isPoint && bounds
                            ? t('viewer.data.pointLocation', {
                                type: feature.geometryType,
                                latitude: bounds[1].toFixed(5),
                                longitude: bounds[0].toFixed(5),
                              })
                            : bounds
                              ? t('viewer.data.geometryExtent', {
                                  type: feature.geometryType,
                                  west: bounds[0].toFixed(5),
                                  south: bounds[1].toFixed(5),
                                  east: bounds[2].toFixed(5),
                                  north: bounds[3].toFixed(5),
                                })
                              : t('viewer.data.geometryType', { type: feature.geometryType })}
                        </p>
                        <h5 className="eyebrow mt-3">
                          {t('viewer.data.attributes')}
                        </h5>
                        {feature.properties.length === 0 ? (
                          <p className="mt-1 text-sm text-muted-foreground">
                            {t('viewer.data.noAttributes')}
                          </p>
                        ) : (
                          <dl className="mt-2 grid gap-x-4 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
                            {feature.properties.map(([key, value]) => (
                              <div key={key} className="min-w-0">
                                <dt className="font-mono text-xs text-muted-foreground">
                                  {humanizeKey(key)}
                                </dt>
                                <dd className="break-words text-sm">
                                  {formatValue(
                                    value,
                                    i18n.language,
                                    t('viewer.data.booleanTrue'),
                                    t('viewer.data.booleanFalse'),
                                  )}
                                </dd>
                              </div>
                            ))}
                          </dl>
                        )}
                      </article>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>
        </div>
      </SheetContent>
    </Sheet>
  );
}
