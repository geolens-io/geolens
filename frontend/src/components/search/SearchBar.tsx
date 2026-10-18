import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { useResetOnEpoch } from '@/hooks/use-reset-on-epoch';
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
  const resetEpoch = useSearchStore((s) => s.resetEpoch);
  // `value` and the epoch it was typed under live in ONE state slot, set
  // together. Deriving the epoch reactively (`useMemo` over
  // `[value, resetEpoch]`) would read the CURRENT epoch in a render where
  // `value` is not yet reset, tearing the pair (new epoch, stale text) when the
  // debounce fires in the same batch as an identity change. Setting both only
  // from the input handlers and the resets below keeps `entry.epoch` the epoch
  // live when `entry.value` was produced.
  const [entry, setEntry] = useState(() => ({ value: query, epoch: resetEpoch }));
  const [showTypeahead, setShowTypeahead] = useState(false);
  const [activeDescendant, setActiveDescendant] = useState<string | null>(null);
  const debouncedEntry = useDebouncedValue(entry, 300);
  const blurTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Rejects a result typed under a no-longer-current identity; the reset
    // below re-arms a debounce for the cleared text under the new epoch.
    if (debouncedEntry.epoch !== useSearchStore.getState().resetEpoch) return;
    useSearchStore.getState().setQuery(debouncedEntry.value);
  }, [debouncedEntry]);

  // Only `value` syncs: an external `q` change is not an identity change, so
  // the epoch is unaffected.
  useEffect(() => {
    setEntry((prev) => ({ ...prev, value: query }));
  }, [query]);

  // An identity change bumps resetEpoch even when `q` was already '', so the
  // `[query]` effect above doesn't fire. Resetting `value` changes
  // useDebouncedValue's input, which cancels its in-flight timer; otherwise a
  // keystroke from the previous identity lands in the new store a few hundred
  // ms later. Shared with FilterPanel/FilterSheet via useResetOnEpoch.
  const resetOnIdentityChange = useCallback(() => {
    const state = useSearchStore.getState();
    setEntry({ value: state.q, epoch: state.resetEpoch });
    setShowTypeahead(false);
    setActiveDescendant(null);
  }, []);
  useResetOnEpoch(resetEpoch, resetOnIdentityChange);

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
          'absolute start-4 top-1/2 -translate-y-1/2 text-muted-foreground/70',
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
        value={entry.value}
        onChange={(e) => {
          setEntry({ value: e.target.value, epoch: useSearchStore.getState().resetEpoch });
          if (e.target.value.length >= 2) {
            setShowTypeahead(true);
          } else {
            setShowTypeahead(false);
          }
        }}
        onFocus={() => {
          if (entry.value.length >= 2) setShowTypeahead(true);
        }}
        onBlur={() => {
          // The delay lets a click on a typeahead result fire first.
          blurTimeoutRef.current = setTimeout(closeTypeahead, 200);
        }}
        placeholder={t('placeholder')}
        className={cn(
          'w-full bg-background text-ellipsis shadow-sm placeholder:text-muted-foreground/75',
          isCompact
            ? 'h-11 rounded-md ps-11 pe-11 text-base'
            : 'h-14 rounded-lg ps-12 pe-12 text-base',
        )}
      />
      {entry.value && (
        <button
          type="button"
          onClick={() => {
            setEntry({ value: '', epoch: useSearchStore.getState().resetEpoch });
            closeTypeahead();
          }}
          aria-label={t('clearSearch', { defaultValue: 'Clear search' })}
          className={cn(
            'absolute end-4 top-1/2 -translate-y-1/2 rounded-full text-muted-foreground/75 transition-colors hover:text-foreground',
            isCompact ? 'p-1' : 'p-1 hover:bg-accent/50',
          )}
        >
          <X className="size-4" />
        </button>
      )}
      {showTypeahead && (
        <SearchTypeahead
          query={entry.value}
          inputRef={inputRef}
          listboxId={typeaheadId}
          onActiveDescendantChange={setActiveDescendant}
          onClose={closeTypeahead}
        />
      )}
    </div>
  );
}
