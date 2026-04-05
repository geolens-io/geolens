import { useRef, useEffect, useState, type ReactNode } from 'react';
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
import { cn } from '@/lib/utils';

interface SearchControlsProps {
  compact?: boolean;
  showFilters: boolean;
  totalResults: number | undefined;
  searchClassName?: string;
  children?: ReactNode;
}

function SearchControls({
  compact = false,
  showFilters,
  totalResults,
  searchClassName,
  children,
}: SearchControlsProps) {
  return (
    <>
      <SearchBar
        mode={compact ? 'compact' : 'hero'}
        className={searchClassName}
      />
      {children ? (
        <div className={compact ? 'mt-3' : 'mt-4 md:mt-5'}>
          {children}
        </div>
      ) : null}
      {showFilters && (
        <div
          className={cn(
            compact
              ? 'mt-2.5 border-t border-border/40 pt-2.5'
              : 'mx-auto mt-5 max-w-5xl border-t border-border/50 pt-4 md:mt-6 md:pt-5',
          )}
        >
          <div className={cn(!compact && 'md:px-1')}>
            <FilterPanel totalResults={totalResults} />
          </div>
        </div>
      )}
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
  const q = useSearchStore((s) => s.q);
  const recordType = useSearchStore((s) => s.record_type);
  const keywords = useSearchStore((s) => s.keywords);
  const geometryType = useSearchStore((s) => s.geometry_type);
  const bbox = useSearchStore((s) => s.bbox);
  const spatialPanelOpen = useSearchStore((s) => s.spatialPanelOpen);

  // Hero collapses when any filter/query is active (user is in browse mode)
  const isLanding = !q && !recordType && keywords.length === 0 && !geometryType && !bbox && !spatialPanelOpen;
  const hasVisibleResults = (data?.features.length ?? 0) > 0;
  const [scrolledPastHero, setScrolledPastHero] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  useUrlSearchSync();

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => setScrolledPastHero(!entry.isIntersecting),
      { threshold: 0 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const showStickyBar = !isLanding || scrolledPastHero;
  const showStickyFilters = !isLanding || (scrolledPastHero && hasVisibleResults);

  return (
    <>
      <div ref={sentinelRef} className="h-0" />
      {showStickyBar && (
        <div
          className="sticky top-0 z-30 border-b border-border/40 bg-background/88 backdrop-blur-lg"
          data-testid="search-sticky-shell"
        >
          <div className="mx-auto max-w-6xl px-4 py-2.5 sm:px-6">
            <div className="rounded-[22px] border border-border/50 bg-background/92 px-3 py-2.5 shadow-sm">
              <SearchControls
                compact
                showFilters={showStickyFilters}
                totalResults={data ? Math.max(data.numberMatched, data.features.length) : undefined}
              />
            </div>
          </div>
        </div>
      )}
      <PageShell maxWidth="wide" className="space-y-6 pb-8 pt-6 sm:pt-8">
        {isLanding && (
          <section className="rounded-[28px] border border-border/60 bg-muted/20 px-4 py-6 sm:px-6 sm:py-7 md:px-8 lg:px-10">
            <div className="mx-auto max-w-4xl space-y-4 md:space-y-6">
              <div className="space-y-2 text-center">
                <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t('title')}</h1>
                <p className="mx-auto max-w-2xl text-sm text-muted-foreground">
                  {t('subtitle')}
                </p>
              </div>
              <SearchControls
                showFilters
                totalResults={data ? Math.max(data.numberMatched, data.features.length) : undefined}
                searchClassName="max-w-4xl"
              >
                {token ? <SavedSearches className="justify-center" /> : null}
              </SearchControls>
            </div>
          </section>
        )}

        {/* Loading indicator for refetch (subtle) */}
        {isFetching && data && (
          <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/85 px-3 py-1.5 text-sm text-muted-foreground shadow-sm">
            <Loader2 className="size-4 animate-spin" />
            {t('updating')}
          </div>
        )}

        {/* Loading state (initial) */}
        {isLoading && !data && (
          <div className="grid gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <DatasetCardSkeleton key={i} />
            ))}
          </div>
        )}

        {/* Error state */}
        {error && (
          <ErrorState message={t('error.message', { message: error.message })} />
        )}

        {/* Empty state — only when there are truly no features to show */}
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

        {/* Results list */}
        {data && data.features.length > 0 && (
          <section className="space-y-4" aria-label={t('results', { defaultValue: 'Search results' })}>
            {data.features.map((feature) => (
              <SearchResultCard key={feature.id} feature={feature} />
            ))}
          </section>
        )}

        {/* Pagination */}
        {data && Math.max(data.numberMatched, data.features.length) > 0 && (
          <Pagination
            total={Math.max(data.numberMatched, data.features.length)}
            offset={offset}
            limit={limit}
            onPageChange={handlePageChange}
          />
        )}
      </PageShell>
    </>
  );
}
