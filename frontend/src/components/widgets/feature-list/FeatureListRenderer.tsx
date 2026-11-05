import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import type { WidgetRenderProps } from '../contract';
import type { FeatureListConfig } from './definition';
import { FeatureText } from './FeatureListFallback';
import { useFeatureRows } from './feature-list-rows';

/**
 * One page of a layer's features as a list, with the next page read when the
 * list's end scrolls into view or "Load more" is pressed. A feature with a
 * shape is a button that asks the host to zoom to it; with no map, or no
 * shape, it is plain text.
 */
export default function FeatureListRenderer({
  config,
  data,
  mapHidden,
  onLoadMore,
  loadingMore,
  loadMoreFailed,
  onZoomTo,
}: WidgetRenderProps<FeatureListConfig>) {
  const { t } = useTranslation('widgets');
  const { rows, hasMore } = useFeatureRows(config, data);
  const end = useRef<HTMLLIElement>(null);
  const loadMore = useRef(onLoadMore);
  loadMore.current = onLoadMore;
  const count = rows?.length ?? 0;

  // Observing again after each page asks for another when the end is still in view.
  useEffect(() => {
    const target = end.current;
    if (!target || !onLoadMore || loadingMore || loadMoreFailed || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) loadMore.current?.();
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, [onLoadMore, loadingMore, loadMoreFailed, count]);

  if (!rows) return <p className="text-sm text-muted-foreground">{t('noData')}</p>;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">{t('noRows')}</p>;

  const mappable = rows.some((row) => row.bbox !== null);
  return (
    <div className="space-y-2">
      <ul
        aria-label={t('types.feature_list.listLabel')}
        className="max-h-80 divide-y overflow-y-auto rounded-md border"
      >
        {rows.map((row) => (
          <li key={row.id}>
            {onZoomTo && row.bbox ? (
              <button
                type="button"
                className="block w-full px-2 py-1.5 text-start hover:bg-accent focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
                onClick={() => onZoomTo({ id: row.id, bbox: row.bbox! })}
              >
                <FeatureText row={row} />
                <span className="sr-only">{t('types.feature_list.zoomTo')}</span>
              </button>
            ) : (
              <div className="px-2 py-1.5">
                <FeatureText row={row} />
              </div>
            )}
          </li>
        ))}
        {hasMore && <li ref={end} aria-hidden="true" className="h-px" />}
      </ul>
      {mapHidden && mappable && <p className="sr-only">{t('types.feature_list.noMap')}</p>}
      <p className="text-xs text-muted-foreground">
        {t(hasMore ? 'types.feature_list.shownMore' : 'types.feature_list.shown', { shown: rows.length })}
      </p>
      {hasMore && loadMoreFailed && (
        <p role="alert" className="text-xs text-destructive">
          {t('types.feature_list.loadFailed')}
        </p>
      )}
      {hasMore && (
        <Button type="button" variant="outline" size="sm" disabled={!onLoadMore || loadingMore} onClick={onLoadMore}>
          {t(loadingMore ? 'types.feature_list.loadingMore' : loadMoreFailed ? 'types.feature_list.retryLoadMore' : 'types.feature_list.loadMore')}
        </Button>
      )}
    </div>
  );
}
