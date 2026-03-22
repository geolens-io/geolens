import { useRef, useEffect, useState } from 'react';
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

export function SearchPage() {
  const { t } = useTranslation('search');
  useDocumentTitle('Search');
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

  const showHero = isLanding && !scrolledPastHero;
  const showStickyBar = !isLanding || scrolledPastHero;

  return (
    <>
      <div ref={sentinelRef} className="h-0" />
      <div className={cn(
        'sticky top-0 z-30 border-b bg-background/95 backdrop-blur-sm transition-all duration-200',
        showStickyBar ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-2 pointer-events-none h-0 overflow-hidden border-b-0',
        showStickyBar && !isLanding ? 'py-2 shadow-sm' : 'py-2.5'
      )}>
        <div className="mx-auto max-w-7xl px-6">
          <div className="max-w-2xl mx-auto [&_input]:h-10 [&_input]:text-base">
            <SearchBar />
          </div>
          {!isLanding && (
            <div className="mt-2">
              <FilterPanel totalResults={data?.numberMatched} />
            </div>
          )}
        </div>
      </div>
    <PageShell maxWidth="wide">
      {/* Hero: only on landing state */}
      {isLanding && (
        <>
          <div className="text-center space-y-2">
            <h1 className="text-2xl font-semibold tracking-tight">{t('title')}</h1>
            <p className="text-muted-foreground text-sm">{t('subtitle')}</p>
          </div>
          <SearchBar />
        </>
      )}

      {/* Saved searches (authenticated users only, landing mode) */}
      {isLanding && token && <SavedSearches />}

      {/* Filters and result count (landing mode only — active mode renders in sticky bar) */}
      {isLanding && <FilterPanel totalResults={data?.numberMatched} />}

      {/* Loading indicator for refetch (subtle) */}
      {isFetching && data && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          {t('updating')}
        </div>
      )}

      {/* Loading state (initial) */}
      {isLoading && !data && (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <DatasetCardSkeleton key={i} />
          ))}
        </div>
      )}

      {/* Error state */}
      {error && (
        <ErrorState message={t('error.message', { message: error.message })} />
      )}

      {/* Empty state */}
      {data && data.numberMatched === 0 && (
        <EmptyState
          icon={SearchX}
          title={t('empty.title')}
          description={t('empty.description')}
          action={
            token ? (
              <Button asChild>
                <Link to="/import">
                  <Upload className="h-4 w-4 mr-1" />
                  {t('empty.cta')}
                </Link>
              </Button>
            ) : undefined
          }
        />
      )}

      {/* Results list */}
      {data && data.features.length > 0 && (
        <div className="space-y-2">
          {data.features.map((feature) => (
            <SearchResultCard key={feature.id} feature={feature} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {data && data.numberMatched > 0 && (
        <Pagination
          total={data.numberMatched}
          offset={offset}
          limit={limit}
          onPageChange={(newOffset) => useSearchStore.getState().setPage(newOffset)}
        />
      )}
    </PageShell>
    </>
  );
}
