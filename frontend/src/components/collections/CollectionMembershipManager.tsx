import { useRef, useState } from 'react';
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
import { distinctDescription } from '@/lib/text';
import { useAuthStore } from '@/stores/auth-store';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { useAddDatasetsToCollection, useCollectionDatasets } from '@/components/collections/hooks/use-collections';

const PAGE_SIZE = 20;
const FILTER_DEBOUNCE_MS = 250;
// CollectionAddDatasetsRequest.dataset_ids is capped at 100 per request.
const ADD_BATCH_SIZE = 100;

/**
 * Sends ids in sequential batches and stops at the first failure or when
 * `shouldContinue` turns false. `ids` are the ids of the batches that
 * succeeded; `count` is the total the server reports adding.
 */
export async function addInBatches(
  ids: string[],
  add: (batch: string[]) => Promise<unknown>,
  batchSize = ADD_BATCH_SIZE,
  shouldContinue: () => boolean = () => true,
): Promise<{ ids: string[]; count: number; failure: unknown }> {
  const done: string[] = [];
  let count = 0;
  for (let i = 0; i < ids.length; i += batchSize) {
    if (!shouldContinue()) break;
    const batch = ids.slice(i, i + batchSize);
    try {
      const res = (await add(batch)) as { added?: number } | undefined;
      count += res?.added ?? batch.length;
    } catch (failure) {
      return { ids: done, count, failure };
    }
    done.push(...batch);
  }
  return { ids: done, count, failure: null };
}

interface CollectionMembershipManagerProps {
  collectionId: string;
}

// Keyed on the collection so selection, filter text and locally added ids never
// carry over when the route reuses this component for another collection.
export function CollectionMembershipManager({ collectionId }: CollectionMembershipManagerProps) {
  return <MembershipPanel key={collectionId} collectionId={collectionId} />;
}

function MembershipPanel({ collectionId }: CollectionMembershipManagerProps) {
  const { t } = useTranslation('collections');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const addDatasets = useAddDatasetsToCollection();
  const { data: datasetsData, dataUpdatedAt } = useCollectionDatasets(collectionId, 0, 200);
  const [justAdded, setJustAdded] = useState<{ ids: Set<string>; at: number }>({
    ids: new Set(),
    at: 0,
  });
  const adding = useRef(false);
  // Hide rows just added until a membership refetch lands after the add; after
  // that the member list is authoritative, so a later removal shows them again.
  // A truncated member list never is, so those rows stay hidden.
  const memberListTruncated =
    !!datasetsData && datasetsData.total > datasetsData.datasets.length;
  const hiddenIds =
    !memberListTruncated && (dataUpdatedAt ?? 0) > justAdded.at ? new Set<string>() : justAdded.ids;
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
    (r) => !memberIds.has(r.id) && !hiddenIds.has(r.id),
  );
  // Checks persist across filter changes, so submit every selection, visible or not.
  const selectedIds = [...selected].filter((id) => !memberIds.has(id) && !hiddenIds.has(id));

  function toggle(id: string, checked: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function handleAdd() {
    if (adding.current || selectedIds.length === 0) return;
    adding.current = true;
    // A different account signing in mid-run must not receive later batches.
    const epoch = useAuthStore.getState().sessionEpoch;
    const sameSession = () => useAuthStore.getState().sessionEpoch === epoch;
    try {
      const { ids, count, failure } = await addInBatches(
        selectedIds,
        (datasetIds) => addDatasets.mutateAsync({ collectionId, datasetIds }),
        ADD_BATCH_SIZE,
        sameSession,
      );
      if (!sameSession()) return;
      if (ids.length > 0) {
        const done = new Set(ids);
        setJustAdded((prev) => ({ ids: new Set([...prev.ids, ...ids]), at: Date.now() }));
        setSelected((prev) => new Set([...prev].filter((id) => !done.has(id))));
        if (count > 0) toast.success(t('membership.added', { count }));
      }
      if (failure) {
        toast.error(failure instanceof Error ? failure.message : t('toasts.addError'));
      }
    } finally {
      adding.current = false;
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
          {available.map((record) => {
            const description = distinctDescription(record.properties.title, record.properties.description);
            return (
            <li key={record.id} className="flex items-center gap-3 px-4 py-3">
              <Checkbox
                id={`membership-${record.id}`}
                checked={selected.has(record.id)}
                onCheckedChange={(v) => toggle(record.id, v === true)}
                aria-label={t('membership.selectAria', { title: record.properties.title })}
              />
              <label htmlFor={`membership-${record.id}`} className="min-w-0 flex-1 cursor-pointer">
                <span className="block truncate text-sm font-medium">{record.properties.title}</span>
                {description && (
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                    {description}
                  </span>
                )}
              </label>
            </li>
            );
          })}
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
        <div className="flex items-center gap-2">
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
          {selectedIds.length > 0 && (
            <Button
              type="button"
              variant="ghost"
              onClick={() => setSelected(new Set())}
              disabled={addDatasets.isPending}
            >
              {t('membership.clearSelection')}
            </Button>
          )}
        </div>
        {candidates.hasNextPage && (
          <Button
            type="button"
            variant="outline"
            onClick={() => candidates.fetchNextPage()}
            disabled={candidates.isFetchingNextPage}
          >
            {candidates.isFetchingNextPage && <Loader2 className="h-4 w-4 me-1 animate-spin" />}
            {t('membership.loadMore')}
          </Button>
        )}
      </div>
    </div>
  );
}
