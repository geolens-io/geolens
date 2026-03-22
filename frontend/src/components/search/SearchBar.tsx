import { useState, useEffect, useRef } from 'react';
import { Search, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { useSearchStore } from '@/stores/search-store';
import { SearchTypeahead } from './SearchTypeahead';

export function SearchBar() {
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
  const closeTypeahead = () => {
    setShowTypeahead(false);
    setActiveDescendant(null);
  };

  return (
    <div className="relative w-full max-w-2xl mx-auto">
      <Search className="absolute left-4 top-1/2 -translate-y-1/2 size-5 text-muted-foreground" />
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
        className="h-12 pl-12 pr-10 text-lg rounded-full border-border/60 shadow-sm focus-visible:ring-primary/30 text-ellipsis"
      />
      {value && (
        <button
          type="button"
          onClick={() => {
            setValue('');
            closeTypeahead();
          }}
          aria-label={t('clearSearch', { defaultValue: 'Clear search' })}
          className="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
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
