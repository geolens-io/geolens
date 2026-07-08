import { type ReactNode, useRef } from 'react';
import { Database, Loader2, SearchX, Upload, X } from 'lucide-react';
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
import { MapCard } from '@/components/maps/MapCard';
import { useSearchResults, useMapSearchResults } from '@/components/search/hooks/use-search';
import { useSearchStore } from '@/stores/search-store';
import { useAuthStore } from '@/stores/auth-store';
import { useUrlSearchSync } from '@/components/search/hooks/use-url-search-sync';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { usePermissions } from '@/hooks/use-permissions';

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
      <div className="mt-3 border-t border-border/40 pt-3 lg:hidden">
        <div className="md:px-1">
          <FilterPanel totalResults={totalResults} showDesktop={false} />
        </div>
      </div>
    </>
  );
}

export function SearchPage() {
  const { t } = useTranslation('search');
  useDocumentTitle(t('common:pageTitle.search'));
  const { data, isLoading, error, isFetching } = useSearchResults();
  // fix(V-08): maps aren't indexed in catalog search — issue a parallel,
  // visibility-scoped lookup against the maps list endpoint so a search for a
  // map's name (e.g. "matterhorn") surfaces it from the home/catalog search.
  const { data: mapResults } = useMapSearchResults();
  const offset = useSearchStore((s) => s.offset);
  const limit = useSearchStore((s) => s.limit);
  const token = useAuthStore((s) => s.token);
  const resetFilters = useSearchStore((s) => s.resetFilters);
  // #305: distinguish an empty catalog from a no-match query. toParams()
  // only emits non-default values, so any key beyond pagination means the user
  // has an active query / filter / sort.
  const hasActiveSearch = useSearchStore((s) =>
    Object.keys(s.toParams()).some((k) => k !== 'offset' && k !== 'limit'),
  );
  const resultsRef = useRef<HTMLDivElement>(null);
  // #305: return to the top of the results (and move focus there for screen
  // readers) on page change — previously the user stayed at the footer.
  const handlePageChange = (newOffset: number) => {
    useSearchStore.getState().setPage(newOffset);
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    resultsRef.current?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
    resultsRef.current?.focus({ preventScroll: true });
  };
  const { can } = usePermissions();
  // fix(GLUX-006): gate the Import CTA on capability, not token presence alone (a
  // viewer with a token must not see a dead-end /import). Keep the `!!token` guard
  // too: on logout the cached ['auth','permissions'] query can briefly still return
  // data, so `can('upload')` may lag true for the now-anonymous session — `token`
  // clears synchronously in the auth store, closing that race. Both conditions =
  // logged in AND allowed. See Navbar.tsx CreateMenu.
  const canImport = !!token && can('upload');
  const totalMatched = data ? Math.max(data.numberMatched ?? 0, data.features.length) : 0;

  useUrlSearchSync();

  return (
    <>
      <h1 className="sr-only">
        {t('workspaceTitle', { defaultValue: 'Search the GeoLens catalog' })}
      </h1>

      <PageShell maxWidth="wide" className="pb-8 pt-5 sm:pt-6">
        <div className="grid gap-5 lg:grid-cols-[18rem_minmax(0,1fr)] xl:grid-cols-[20rem_minmax(0,1fr)]">
          <aside className="hidden lg:block">
            <div className="sticky top-16 max-h-[calc(100vh-5rem)] overflow-y-auto">
              <FilterPanel
                totalResults={totalMatched > 0 ? totalMatched : undefined}
                showMobile={false}
                desktopLayout="rail"
              />
            </div>
          </aside>

          <div className="min-w-0 space-y-5">
            <section className="rounded-lg border bg-card px-4 py-4 shadow-sm sm:px-5">
              <SearchControls totalResults={totalMatched > 0 ? totalMatched : undefined}>
                {token ? <SavedSearches className="justify-center md:justify-start" /> : null}
              </SearchControls>
            </section>

            {isFetching && data && (
              <div role="status" aria-live="polite" className="inline-flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-sm text-muted-foreground shadow-sm">
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                {t('updating')}
              </div>
            )}

            {isLoading && !data && (
              <div role="status" aria-live="polite" className="grid gap-3">
                <span className="sr-only">{t('loadingDatasets')}</span>
                {Array.from({ length: 4 }).map((_, i) => (
                  <DatasetCardSkeleton key={i} />
                ))}
              </div>
            )}

            {error && (
              <ErrorState message={t('error.message', { message: error.message })} />
            )}

            {/* fix(V-08): rendered independent of the dataset result state above —
                a query can match a map with zero matching datasets. */}
            {mapResults && mapResults.maps.length > 0 && (
              <section className="space-y-3" aria-label={t('mapsSectionTitle', { defaultValue: 'Maps' })}>
                <h2 className="text-sm font-medium text-foreground px-0.5">
                  {t('mapsSectionTitle', { defaultValue: 'Maps' })}
                </h2>
                <div className="grid gap-3 sm:grid-cols-2">
                  {mapResults.maps.map((map) => (
                    <MapCard key={map.id} map={map} />
                  ))}
                </div>
              </section>
            )}

            {data && data.features.length === 0 && (
              // #305: only the true empty-catalog case (no matches at all, no
              // query) gets onboarding. A positive totalMatched with an empty
              // page means an out-of-range offset (e.g. stale /?offset=1000) —
              // show the no-results state (Clear resets offset to page 1).
              hasActiveSearch || totalMatched > 0 ? (
                <EmptyState
                  icon={SearchX}
                  title={t('empty.title')}
                  description={t('empty.description')}
                  action={
                    <Button variant="outline" onClick={() => resetFilters()}>
                      <X className="h-4 w-4 me-1" />
                      {t('empty.clear', { defaultValue: 'Clear search & filters' })}
                    </Button>
                  }
                />
              ) : (
                <EmptyState
                  icon={Database}
                  title={t('empty.catalogTitle', { defaultValue: 'Your catalog is empty' })}
                  description={t('empty.catalogDescription', {
                    defaultValue: 'Import a dataset to start building your geospatial catalog.',
                  })}
                  action={
                    canImport ? (
                      <Button asChild>
                        <Link to="/import">
                          <Upload className="h-4 w-4 me-1" />
                          {t('empty.cta')}
                        </Link>
                      </Button>
                    ) : undefined
                  }
                />
              )
            )}

            {data && data.features.length > 0 && (
              <div ref={resultsRef} tabIndex={-1} className="scroll-mt-20 space-y-3 outline-none">
                {/* #305: in-context results header — visible at all widths,
                    unlike the count that previously lived only in the desktop rail. */}
                <div className="flex items-center justify-between gap-3 px-0.5">
                  <h2 className="text-sm font-medium text-foreground">
                    {t('resultCount', { count: totalMatched })}
                  </h2>
                </div>
                <section className="space-y-3" aria-label={t('results', { defaultValue: 'Search results' })}>
                  {data.features.map((feature) => (
                    <SearchResultCard key={feature.id} feature={feature} />
                  ))}
                </section>
              </div>
            )}

            {data && totalMatched > 0 && (
              <Pagination
                total={totalMatched}
                offset={offset}
                limit={limit}
                onPageChange={handlePageChange}
              />
            )}
          </div>
        </div>
      </PageShell>
    </>
  );
}
