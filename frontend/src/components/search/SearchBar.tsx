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
  // fix(#1761 review round 6): `value` and the epoch it was typed under
  // travel together in ONE state slot, set atomically by the same call.
  // Round 4's fix derived the paired epoch reactively (`useMemo` over
  // `[value, resetEpoch]`), which reads the CURRENT `resetEpoch` even in a
  // render where `value` has not been reset yet — codex reproduced exactly
  // that torn intermediate pairing (new epoch, stale text) by advancing the
  // debounce timer in the same batch as an identity change. Setting both
  // fields together, only from the input's own onChange/clear handlers and
  // from the resets below, means `entry.epoch` can only ever be the epoch
  // that was live at the moment `entry.value` was actually produced.
  const [entry, setEntry] = useState(() => ({ value: query, epoch: resetEpoch }));
  const [showTypeahead, setShowTypeahead] = useState(false);
  const [activeDescendant, setActiveDescendant] = useState<string | null>(null);
  const debouncedEntry = useDebouncedValue(entry, 300);
  const blurTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // fix(#1761 review round 6): reject a debounced result whose captured
    // epoch no longer matches the live one — it was typed under an
    // identity that is no longer current. The reset below re-arms a fresh
    // debounce for the cleared text under the new epoch.
    if (debouncedEntry.epoch !== useSearchStore.getState().resetEpoch) return;
    useSearchStore.getState().setQuery(debouncedEntry.value);
  }, [debouncedEntry]);

  // Sync external store changes (e.g., reset filters) back to local state.
  // Only `value` — an external `q` change is not itself an identity change,
  // so the epoch this typed-or-cleared text is stamped with is unaffected.
  useEffect(() => {
    setEntry((prev) => ({ ...prev, value: query }));
  }, [query]);

  // fix(#1761 review P2, extracted round 4): an identity change bumps
  // resetEpoch even when `q` was already '' (nothing had been committed to
  // the store yet), so the `[query]` effect above sees no change and does
  // not fire. Resetting `value` here changes useDebouncedValue's input,
  // which is what actually cancels its in-flight timer (see
  // useDebouncedValue's cleanup) — without this, a keystroke typed under
  // the previous identity still lands in the new identity's store a few
  // hundred ms later. Shared with FilterPanel/FilterSheet via
  // useResetOnEpoch — see that hook for the skip-on-mount rationale.
  const resetOnIdentityChange = useCallback(() => {
    const state = useSearchStore.getState();
    setEntry({ value: state.q, epoch: state.resetEpoch });
    setShowTypeahead(false);
    setActiveDescendant(null);
  }, []);
  useResetOnEpoch(resetEpoch, resetOnIdentityChange);

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
          // Small delay so click on typeahead result can fire first
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
