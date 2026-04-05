import { type ReactNode } from 'react';
import { Loader2, SearchX, Upload } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { PageShell } from '@/components/layout/PageShell';
import { ErrorState } from '@/components/layout/ErrorState';
import { EmptyState } from '@/components/layout/EmptyState';
import { Button } from '@/components/ui/button';
import { SearchBar } from '@/components/search/SearchBar';
import { SavedSearches } from '@/components/search/SavedSearches';
import { FilterPanel } from '@/components/search/FilterPanel';
import { SearchResultCard } from '@/components/search/SearchResultCard';
import { DatasetCardSkeleton } from '@/components/search/DatasetCardSkeleton';
import { Pagination } from '@/components/layout/Pagination';
import { useSearchResults } from '@/hooks/use-search';
import { useSearchStore } from '@/stores/search-store';
import { useAuthStore } from '@/stores/auth-store';
import { useUrlSearchSync } from '@/hooks/use-url-search-sync';
import { useDocumentTitle } from '@/hooks/use-document-title';

interface SearchControlsProps {
  totalResults: number | undefined;
  children?: ReactNode;
}

function SearchControls({ totalResults, children }: SearchControlsProps) {
  return (
    <>
      <SearchBar mode="compact" />
      {children ? (
        <div className="mt-3">
          {children}
        </div>
      ) : null}
      <div className="mt-3 border-t border-border/40 pt-3">
        <div className="md:px-1">
          <FilterPanel totalResults={totalResults} />
        </div>
      </div>
    </>
  );
}

function handlePageChange(offset: number) {
  useSearchStore.getState().setPage(offset);
}

export function SearchPage() {
  const { t } = useTranslation('search');
  useDocumentTitle(t('common:pageTitle.search'));
  const { data, isLoading, error, isFetching } = useSearchResults();
  const offset = useSearchStore((s) => s.offset);
  const limit = useSearchStore((s) => s.limit);
  const token = useAuthStore((s) => s.token);
  const totalMatched = data ? Math.max(data.numberMatched ?? 0, data.features.length) : 0;

  useUrlSearchSync();

  return (
    <>
      <h1 className="sr-only">
        {t('workspaceTitle', { defaultValue: 'Search the GeoLens catalog' })}
      </h1>

      <PageShell maxWidth="wide" className="space-y-5 pb-8 pt-5 sm:pt-6">
        <section className="rounded-[22px] border border-border/50 bg-background/95 px-4 py-4 shadow-sm sm:px-5">
          <SearchControls totalResults={totalMatched > 0 ? totalMatched : undefined}>
            {token ? <SavedSearches className="justify-center md:justify-start" /> : null}
          </SearchControls>
        </section>

        {isFetching && data && (
          <div role="status" aria-live="polite" className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/85 px-3 py-1.5 text-sm text-muted-foreground shadow-sm">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            {t('updating')}
          </div>
        )}

        {isLoading && !data && (
          <div role="status" aria-live="polite" className="grid gap-4">
            <span className="sr-only">{t('loadingDatasets')}</span>
            {Array.from({ length: 4 }).map((_, i) => (
              <DatasetCardSkeleton key={i} />
            ))}
          </div>
        )}

        {error && (
          <ErrorState message={t('error.message', { message: error.message })} />
        )}

        {data && data.features.length === 0 && (
          <EmptyState
            icon={SearchX}
            title={t('empty.title')}
            description={t('empty.description')}
            action={
              token ? (
                <Button asChild>
                  <Link to="/import">
                    <Upload className="h-4 w-4 me-1" />
                    {t('empty.cta')}
                  </Link>
                </Button>
              ) : undefined
            }
          />
        )}

        {data && data.features.length > 0 && (
          <section className="scroll-mt-24 space-y-4" aria-label={t('results', { defaultValue: 'Search results' })}>
            {data.features.map((feature) => (
              <SearchResultCard key={feature.id} feature={feature} />
            ))}
          </section>
        )}

        {data && totalMatched > 0 && (
          <Pagination
            total={totalMatched}
            offset={offset}
            limit={limit}
            onPageChange={handlePageChange}
          />
        )}
      </PageShell>
    </>
  );
}
