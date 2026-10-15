import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query';
import { Search, Plus, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { FieldLabel } from '@/components/ui/field-label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { LiveAnnouncement } from '@/components/ui/live-announcement';
import { searchDatasets } from '@/api/search';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { useAddDatasetsToCollection, useCollectionDatasets } from '@/components/collections/hooks/use-collections';

const PAGE_SIZE = 20;
const FILTER_DEBOUNCE_MS = 250;
// CollectionAddDatasetsRequest.dataset_ids is capped at 100 per request.
const ADD_BATCH_SIZE = 100;

/** Sends ids in sequential batches; stops at the first failure and reports what was added. */
export async function addInBatches(
  ids: string[],
  add: (batch: string[]) => Promise<unknown>,
  batchSize = ADD_BATCH_SIZE,
): Promise<{ added: string[]; failure: unknown }> {
  const added: string[] = [];
  for (let i = 0; i < ids.length; i += batchSize) {
    const batch = ids.slice(i, i + batchSize);
    try {
      await add(batch);
    } catch (failure) {
      return { added, failure };
    }
    added.push(...batch);
  }
  return { added, failure: null };
}

interface CollectionMembershipManagerProps {
  collectionId: string;
}

export function CollectionMembershipManager({
  collectionId,
}: CollectionMembershipManagerProps) {
  const { t } = useTranslation('collections');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const addDatasets = useAddDatasetsToCollection();
  const { data: datasetsData } = useCollectionDatasets(collectionId, 0, 200);
  const memberIds = new Set(datasetsData?.datasets.map((d) => d.id) ?? []);
  const q = useDebouncedValue(query.trim(), FILTER_DEBOUNCE_MS);

  const candidates = useInfiniteQuery({
    queryKey: ['collections', 'membership-candidates', q],
    initialPageParam: 0,
    placeholderData: keepPreviousData,
    queryFn: async ({ pageParam, signal }) => {
      const params: Record<string, string> = {
        sort_by: 'date_added',
        sort_desc: 'true',
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
      };
      if (q) params.q = q;
      const res = await searchDatasets(params, { signal });
      // A text search also returns up to five matching collections on page 0.
      return {
        features: res.features.filter((f) => f.properties.type !== 'collection'),
        hasNext: res.links?.some((l) => l.rel === 'next') ?? false,
      };
    },
    // numberMatched also counts matching collections, so the dataset-only
    // `next` link decides whether another page exists.
    getNextPageParam: (last, _pages, lastOffset) => (last.hasNext ? lastOffset + PAGE_SIZE : undefined),
  });

  const available = (candidates.data?.pages.flatMap((p) => p.features) ?? []).filter(
    (r) => !memberIds.has(r.id),
  );
  // Checks persist across filter changes, so submit every selection, visible or not.
  const selectedIds = [...selected].filter((id) => !memberIds.has(id));

  function toggle(id: string, checked: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function handleAdd() {
    const { added, failure } = await addInBatches(selectedIds, (datasetIds) =>
      addDatasets.mutateAsync({ collectionId, datasetIds }),
    );
    if (added.length > 0) {
      const done = new Set(added);
      toast.success(t('membership.added', { count: added.length }));
      setSelected((prev) => new Set([...prev].filter((id) => !done.has(id))));
    }
    if (failure) {
      toast.error(failure instanceof Error ? failure.message : t('toasts.addError'));
    }
  }

  const loading = candidates.isPending;
  const emptyKey = q ? 'membership.noMatches' : 'membership.empty';

  return (
    <div className="space-y-4">
      <h3 className="text-base font-semibold">{t('membership.title')}</h3>

      <div className="relative">
        <FieldLabel htmlFor="collection-membership-search">
          {t('membership.searchPlaceholder')}
        </FieldLabel>
        <Search className="absolute start-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input
          id="collection-membership-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('membership.searchPlaceholder')}
          className="ps-9"
        />
      </div>

      {loading && (
        <p className="flex items-center justify-center gap-2 py-4 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('membership.loading')}
        </p>
      )}

      {candidates.isError && (
        <p role="alert" className="py-4 text-center text-sm text-destructive">
          {t('membership.loadError')}
        </p>
      )}

      {available.length > 0 && (
        <ul aria-label={t('membership.listLabel')} className="divide-y rounded-md border">
          {available.map((record) => (
            <li key={record.id} className="flex items-center gap-3 px-4 py-3">
              <Checkbox
                id={`membership-${record.id}`}
                checked={selected.has(record.id)}
                onCheckedChange={(v) => toggle(record.id, v === true)}
                aria-label={t('membership.selectAria', { title: record.properties.title })}
              />
              <label htmlFor={`membership-${record.id}`} className="min-w-0 flex-1 cursor-pointer">
                <span className="block truncate text-sm font-medium">{record.properties.title}</span>
                {record.properties.description && (
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                    {record.properties.description}
                  </span>
                )}
              </label>
            </li>
          ))}
        </ul>
      )}

      {!loading && !candidates.isError && available.length === 0 && (
        <p className="py-4 text-center text-sm text-muted-foreground">{t(emptyKey)}</p>
      )}

      <LiveAnnouncement
        text={loading ? '' : t('membership.resultCount', { count: available.length })}
        delayMs={300}
        trigger={q}
      />

      <div className="flex items-center justify-between gap-2">
        <Button
          type="button"
          onClick={handleAdd}
          disabled={selectedIds.length === 0 || addDatasets.isPending}
        >
          {addDatasets.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4 me-1" />
          )}
          {t('membership.addSelected', { count: selectedIds.length })}
        </Button>
        {candidates.hasNextPage && (
          <Button
            type="button"
            variant="outline"
            onClick={() => candidates.fetchNextPage()}
            disabled={candidates.isFetchingNextPage}
          >
            {candidates.isFetchingNextPage ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              t('membership.loadMore')
            )}
          </Button>
        )}
      </div>
    </div>
  );
}
