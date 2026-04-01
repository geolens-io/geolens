import { useState, useEffect, useCallback, useMemo, type RefObject } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { searchDatasets } from '@/api/search';
import { queryKeys } from '@/lib/query-keys';
import { geometryIcon } from '@/lib/geo-utils';

interface SearchTypeaheadProps {
  query: string;
  inputRef: RefObject<HTMLInputElement | null>;
  listboxId?: string;
  onActiveDescendantChange: (id: string | null) => void;
  onClose: () => void;
}

export function SearchTypeahead({
  query,
  inputRef,
  listboxId,
  onActiveDescendantChange,
  onClose,
}: SearchTypeaheadProps) {
  const { t } = useTranslation('search');
  const navigate = useNavigate();
  const debouncedQuery = useDebouncedValue(query, 300);
  const [activeIndex, setActiveIndex] = useState(-1);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.typeahead.results(debouncedQuery),
    queryFn: () => searchDatasets({ q: debouncedQuery, limit: '5' }),
    enabled: debouncedQuery.length >= 2,
    staleTime: 10_000,
  });

  const results = useMemo(() => data?.features ?? [], [data?.features]);

  // Reset active index when results change
  useEffect(() => {
    setActiveIndex(-1);
  }, [debouncedQuery]);

  useEffect(() => {
    onActiveDescendantChange(
      activeIndex >= 0 ? `typeahead-option-${activeIndex}` : null,
    );
  }, [activeIndex, onActiveDescendantChange]);

  useEffect(() => {
    return () => onActiveDescendantChange(null);
  }, [onActiveDescendantChange]);

  const selectResult = useCallback(
    (id: string) => {
      onClose();
      navigate(`/datasets/${id}`);
    },
    [navigate, onClose],
  );

  // Keyboard navigation
  useEffect(() => {
    const input = inputRef.current;

    if (!input) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (results.length === 0) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveIndex((prev) => (prev < results.length - 1 ? prev + 1 : 0));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveIndex((prev) => (prev > 0 ? prev - 1 : results.length - 1));
      } else if (e.key === 'Enter' && activeIndex >= 0) {
        e.preventDefault();
        selectResult(results[activeIndex].id);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    }

    input.addEventListener('keydown', handleKeyDown);
    return () => input.removeEventListener('keydown', handleKeyDown);
  }, [results, activeIndex, inputRef, selectResult, onClose]);

  // Don't render when query is too short or when there are no results
  // (the page-level EmptyState handles the zero-results case)
  if (debouncedQuery.length < 2) return null;
  if (!isLoading && results.length === 0) return null;

  return (
    <div
      id={listboxId}
      role="listbox"
      className="absolute left-0 right-0 top-full z-50 mt-2 overflow-hidden rounded-[22px] border border-border/70 bg-popover/98 text-popover-foreground shadow-xl backdrop-blur-sm"
    >
      {isLoading && (
        <div className="flex items-center gap-2 px-4 py-3 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          {t('typeahead.searching')}
        </div>
      )}

      {/* No-results message suppressed — the page-level EmptyState handles this */}

      {!isLoading &&
        results.map((feature, index) => {
          const Icon = geometryIcon(feature.properties.geometry_type);
          return (
            <button
              key={feature.id}
              id={`typeahead-option-${index}`}
              type="button"
              role="option"
              aria-selected={index === activeIndex}
              onMouseDown={(e) => {
                e.preventDefault(); // Prevent blur before click fires
                selectResult(feature.id);
              }}
              onMouseEnter={() => setActiveIndex(index)}
              className={`flex w-full items-center gap-3 px-4 py-2.5 text-start text-sm transition-colors duration-150 ${
                index === activeIndex
                  ? 'bg-accent text-accent-foreground'
                  : 'hover:bg-accent/50'
              }`}
            >
              {Icon && (
                <Icon className="size-4 shrink-0 text-muted-foreground" />
              )}
              <span className="truncate">{feature.properties.title}</span>
            </button>
          );
        })}
    </div>
  );
}
