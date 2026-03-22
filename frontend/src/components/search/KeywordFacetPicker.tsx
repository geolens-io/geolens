import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Tag } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Skeleton } from '@/components/ui/skeleton';
import { useSearchStore } from '@/stores/search-store';
import type { FacetItem } from '@/types/api';

interface KeywordFacetPickerProps {
  facets: FacetItem[] | undefined;
  isLoading: boolean;
}

export function KeywordFacetPicker({ facets, isLoading }: KeywordFacetPickerProps) {
  const { t } = useTranslation('search');
  const selectedKeywords = useSearchStore((s) => s.keywords);
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);

  const filtered = useMemo(() => {
    if (!facets) return [];
    if (!search) return facets;
    const lower = search.toLowerCase();
    return facets.filter((f) => f.value.toLowerCase().includes(lower));
  }, [facets, search]);

  const toggleKeyword = (kw: string) => {
    const current = useSearchStore.getState().keywords;
    const next = current.includes(kw)
      ? current.filter((k) => k !== kw)
      : [...current, kw];
    useSearchStore.getState().setFilter('keywords', next);
  };

  const clearAll = () => {
    useSearchStore.getState().setFilter('keywords', []);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm">
          <Tag className="mr-1 size-3.5" />
          {t('filters.keywords', { defaultValue: 'Keywords' })}
          {selectedKeywords.length > 0 && (
            <span className="ml-1 rounded-full bg-primary px-1.5 py-0 text-[11px] font-semibold text-primary-foreground">
              {selectedKeywords.length}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-72 p-0">
        <div className="p-3 pb-2">
          <Input
            placeholder={t('filters.keywordSearch', { defaultValue: 'Search keywords...' })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 text-sm"
          />
        </div>
        <div className="max-h-[280px] overflow-y-auto px-3">
          {isLoading && (
            <div className="space-y-2 py-2">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-5 w-36" />
            </div>
          )}
          {!isLoading && filtered.length === 0 && (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t('filters.noKeywords', { defaultValue: 'No keywords available' })}
            </p>
          )}
          {!isLoading &&
            filtered.map((item) => (
              <label
                key={item.value}
                className="flex cursor-pointer items-center gap-2 rounded-sm px-1 py-1.5 text-sm hover:bg-accent/50"
              >
                <Checkbox
                  checked={selectedKeywords.includes(item.value)}
                  onCheckedChange={() => toggleKeyword(item.value)}
                />
                <span className="flex-1 truncate">{item.value}</span>
                <span className="text-xs text-muted-foreground">({item.count})</span>
              </label>
            ))}
        </div>
        {selectedKeywords.length > 0 && (
          <div className="border-t p-2">
            <Button variant="ghost" size="sm" className="w-full" onClick={clearAll}>
              {t('filters.clearKeywords', { defaultValue: 'Clear all' })}
            </Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
