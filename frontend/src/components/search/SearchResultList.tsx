import { Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import { SearchResultCard } from './SearchResultCard';
import type { SearchResultDensity } from '@/lib/search-view';
import type { OGCRecordResponse } from '@/types/api';

/** The compact list's frame; the loading skeleton uses it too. */
export const compactListPanel = 'overflow-hidden rounded-lg border border-border/60 bg-card shadow-sm';

// One grid for the whole list, so the detail and date columns take the width
// of their widest entry on the page and the name gets the rest.
const compactGrid = 'md:grid md:grid-cols-[auto_minmax(0,1fr)_max-content_max-content] md:gap-x-3';
const gridRow = 'md:col-span-full md:grid md:grid-cols-subgrid';

interface SearchResultListProps {
  features: OGCRecordResponse[];
  density: SearchResultDensity;
}

export function SearchResultList({ features, density }: SearchResultListProps) {
  const { t } = useTranslation('search');

  if (density !== 'compact') {
    return (
      <ul className="space-y-3">
        {features.map((feature) => (
          <li key={feature.id}>
            <SearchResultCard feature={feature} />
          </li>
        ))}
      </ul>
    );
  }

  const firstCollection = features.findIndex((feature) => feature.properties?.record_type === 'collection');

  return (
    <div className={`${compactListPanel} ${compactGrid}`}>
      {/* Each row's link already names its type and says "Updated", so the
          heads are for sighted readers only. */}
      <div
        aria-hidden="true"
        className={`hidden items-center border-b border-border/60 bg-muted/40 px-3 py-1.5 ${gridRow}`}
        data-testid="search-result-columns"
      >
        <span />
        <span className="eyebrow">{t('compactColumns.name')}</span>
        <span className="eyebrow">{t('compactColumns.details')}</span>
        <span className="eyebrow text-end">{t('compactColumns.updated')}</span>
      </div>
      <ul className={gridRow}>
        {features.map((feature, index) => (
          <Fragment key={feature.id}>
            {index > 0 && index === firstCollection && (
              // The page range counts datasets; this marks where the matching
              // collections begin. Each link already names its type.
              <li
                aria-hidden="true"
                className="border-t border-border/60 bg-muted/40 px-3 py-1.5 md:col-span-full"
                data-testid="search-result-collections"
              >
                <span className="eyebrow">{t('compactColumns.collections')}</span>
              </li>
            )}
            <li className={`border-t border-border/60 first:border-t-0 ${gridRow}`}>
              <SearchResultCard feature={feature} density="compact" />
            </li>
          </Fragment>
        ))}
      </ul>
    </div>
  );
}
