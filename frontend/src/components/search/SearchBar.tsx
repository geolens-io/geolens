import { useState, useEffect, useRef } from 'react';
import { Search, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { useSearchStore } from '@/stores/search-store';
import { cn } from '@/lib/utils';
import { SearchTypeahead } from './SearchTypeahead';

interface SearchBarProps {
  mode?: 'hero' | 'compact';
  className?: string;
}

export function SearchBar({ mode = 'hero', className }: SearchBarProps) {
  const { t } = useTranslation('search');
  const query = useSearchStore((s) => s.q);
  const [value, setValue] = useState(query);
  const [showTypeahead, setShowTypeahead] = useState(false);
  const [activeDescendant, setActiveDescendant] = useState<string | null>(null);
  const debouncedValue = useDebouncedValue(value, 300);
  const blurTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    useSearchStore.getState().setQuery(debouncedValue);
  }, [debouncedValue]);

  // Sync external store changes (e.g., reset filters) back to local state
  useEffect(() => {
    setValue(query);
  }, [query]);

  // Cleanup blur timeout on unmount
  useEffect(() => {
    return () => {
      if (blurTimeoutRef.current) clearTimeout(blurTimeoutRef.current);
    };
  }, []);

  const typeaheadId = 'search-typeahead-listbox';
  const isCompact = mode === 'compact';
  const closeTypeahead = () => {
    setShowTypeahead(false);
    setActiveDescendant(null);
  };

  return (
    <div
      className={cn(
        'relative mx-auto w-full',
        isCompact ? 'max-w-none' : 'max-w-3xl',
        className,
      )}
    >
      <Search
        className={cn(
          'absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground/80',
          isCompact ? 'size-[18px]' : 'size-5',
        )}
      />
      <Input
        ref={inputRef}
        role="combobox"
        aria-expanded={showTypeahead}
        aria-haspopup="listbox"
        aria-autocomplete="list"
        aria-label={t('placeholder')}
        aria-controls={showTypeahead ? typeaheadId : undefined}
        aria-activedescendant={showTypeahead ? activeDescendant ?? undefined : undefined}
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          if (e.target.value.length >= 2) {
            setShowTypeahead(true);
          } else {
            setShowTypeahead(false);
          }
        }}
        onFocus={() => {
          if (value.length >= 2) setShowTypeahead(true);
        }}
        onBlur={() => {
          // Small delay so click on typeahead result can fire first
          blurTimeoutRef.current = setTimeout(closeTypeahead, 200);
        }}
        placeholder={t('placeholder')}
        className={cn(
          'w-full border-border/60 bg-background/95 text-ellipsis shadow-[0_10px_30px_-24px_rgba(15,23,42,0.55)] placeholder:text-muted-foreground/80 focus-visible:ring-primary/20',
          isCompact
            ? 'h-11 rounded-[22px] pl-11 pr-11 text-base'
            : 'h-14 rounded-[28px] pl-12 pr-12 text-base sm:h-16 sm:text-lg',
        )}
      />
      {value && (
        <button
          type="button"
          onClick={() => {
            setValue('');
            closeTypeahead();
          }}
          aria-label={t('clearSearch', { defaultValue: 'Clear search' })}
          className={cn(
            'absolute right-4 top-1/2 -translate-y-1/2 rounded-full text-muted-foreground transition-colors hover:text-foreground',
            isCompact ? 'p-0' : 'p-0.5 hover:bg-accent/60',
          )}
        >
          <X className="size-4" />
        </button>
      )}
      {showTypeahead && (
        <SearchTypeahead
          query={value}
          inputRef={inputRef}
          listboxId={typeaheadId}
          onActiveDescendantChange={setActiveDescendant}
          onClose={closeTypeahead}
        />
      )}
    </div>
  );
}
