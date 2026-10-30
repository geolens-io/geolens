/* eslint-disable jsx-a11y/no-noninteractive-tabindex -- the named overflow region must be keyboard-scrollable */
import { RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { LiveAnnouncement } from '@/components/ui/live-announcement';
import type { SharedLayerResponse } from '@/types/api';
import { createViewerLayerEntries } from '@/components/viewer/layer-identity';
import { formatFeaturePropertyValue } from '@/lib/feature-property-value';
import type { AccessibleMapFeatureResult } from './accessible-map-data';

interface AccessibleMapDataPanelProps {
  layers: SharedLayerResponse[];
  visibleLayers: Set<string>;
  featureResult: AccessibleMapFeatureResult;
  onRefresh: () => void;
  /** True only when every layer's dataset is public, so linking to dataset pages cannot expose a private id. */
  datasetLinksAllowed?: boolean;
  /**
   * Keys of the layers the Map data table can show. With `onOpenTable`, a
   * capped list offers to open these in the table instead of dataset links.
   */
  tableLayerKeys?: ReadonlySet<string>;
  onOpenTable?: (layerKey: string) => void;
}

const SUMMARY_ANNOUNCE_DELAY_MS = 1000;

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
  useGrouping: boolean,
): string {
  // 5 fraction digits (not the shared default of 4): this panel is the
  // accessible surface for raw feature coordinates, so it keeps the more
  // precise formatting.
  return formatFeaturePropertyValue(value, locale, booleanTrue, booleanFalse, 5, useGrouping) ?? '—';
}

export function AccessibleMapDataPanel({
  layers,
  visibleLayers,
  featureResult,
  onRefresh,
  datasetLinksAllowed = false,
  tableLayerKeys,
  onOpenTable,
}: AccessibleMapDataPanelProps) {
  const { t, i18n } = useTranslation('common');
  const layerEntries = createViewerLayerEntries(layers);
  const tableLinks = featureResult.truncated && onOpenTable
    ? layerEntries.filter(({ key }) => visibleLayers.has(key) && tableLayerKeys?.has(key))
    : [];
  // The data tab lists vector rows only, and a dataset used by two layers needs one link.
  const dataLinks = featureResult.truncated && datasetLinksAllowed && tableLinks.length === 0
    ? [...new Map(
        layerEntries
          .filter(({ layer, key }) => visibleLayers.has(key) && layer.layer_type !== 'raster_geolens')
          .map(({ layer }) => [layer.dataset_id, layer.display_name || layer.dataset_name] as const),
      )]
    : [];
  const resultSummary = featureResult.truncated
    ? t('viewer.data.resultSummaryTruncated', {
        shown: featureResult.features.length,
        total: featureResult.total,
      })
    : t('viewer.data.resultSummary', { count: featureResult.total });

  return (
    // The panel is a real overflow region; make it keyboard-scrollable and
    // give it a programmatic name for WCAG 2.1.1/2.4.3.
    <div
      className="min-h-0 flex-1 overflow-y-auto p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      tabIndex={0}
      role="region"
      aria-label={t('viewer.data.scrollLabel')}
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm text-muted-foreground">{t('viewer.data.description')}</p>
        <Button type="button" variant="outline" size="sm" className="pointer-coarse:min-h-11" onClick={onRefresh}>
          <RefreshCw aria-hidden="true" />
          {t('viewer.data.refresh')}
        </Button>
      </div>
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
          <p className="text-xs text-muted-foreground" aria-hidden="true">{resultSummary}</p>
          {/* The map refreshes this on every idle; the delay debounces the announcement. */}
          <LiveAnnouncement text={resultSummary} delayMs={SUMMARY_ANNOUNCE_DELAY_MS} />
        </div>

        {featureResult.truncated && (
          <div className="mt-3 rounded-md border bg-muted/40 p-3 text-sm">
            <p>{t('viewer.data.truncatedHint')}</p>
            {tableLinks.length > 0 && (
              <ul className="mt-2 space-y-1">
                {tableLinks.map(({ layer, key }) => (
                  <li key={key}>
                    <button
                      type="button"
                      className="cursor-pointer text-start text-primary underline pointer-coarse:min-h-11"
                      onClick={() => onOpenTable?.(key)}
                    >
                      {t('viewer.data.openInTable', { name: layer.display_name || layer.dataset_name })}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {dataLinks.length > 0 && (
              <ul className="mt-2 space-y-1">
                {dataLinks.map(([datasetId, name]) => (
                  <li key={datasetId}>
                    <a
                      href={`/datasets/${encodeURIComponent(datasetId)}#data`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary underline"
                    >
                      {t('viewer.data.openDatasetData', { name })}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

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
                                !feature.ungroupedKeys.has(key),
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
  );
}
