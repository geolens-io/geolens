import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Search, Plus, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { FieldLabel } from '@/components/ui/field-label';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { searchDatasets } from '@/api/search';
import { useAddDatasetsToCollection, useCollectionDatasets } from '@/components/collections/hooks/use-collections';

interface CollectionMembershipManagerProps {
  collectionId: string;
}

export function CollectionMembershipManager({
  collectionId,
}: CollectionMembershipManagerProps) {
  const { t } = useTranslation('collections');
  const [query, setQuery] = useState('');
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [addingId, setAddingId] = useState<string | null>(null);
  const [addedIds, setAddedIds] = useState<string[]>([]);
  const addDatasets = useAddDatasetsToCollection();
  const { data: datasetsData } = useCollectionDatasets(collectionId, 0, 200);
  const currentDatasetIds = datasetsData?.datasets.map((d) => d.id) ?? [];
  // Once the membership list shows an added dataset it covers it, so a later
  // removal makes the dataset addable again.
  useEffect(() => {
    setAddedIds((prev) => {
      const next = prev.filter((id) => !currentDatasetIds.includes(id));
      return next.length === prev.length ? prev : next;
    });
  }, [datasetsData]); // eslint-disable-line react-hooks/exhaustive-deps -- currentDatasetIds derives from datasetsData
  const {
    data: searchData,
    isFetching: searching,
    refetch,
  } = useQuery({
    queryKey: ['collection-membership-search', submittedQuery],
    queryFn: ({ signal }) => searchDatasets({ q: submittedQuery, limit: '10' }, { signal }),
    enabled: submittedQuery !== '',
    retry: false,
  });
  const results = searchData?.features ?? [];

  function handleSearch() {
    const q = query.trim();
    if (!q) return;
    if (q === submittedQuery) void refetch();
    else setSubmittedQuery(q);
  }

  async function handleAdd(datasetId: string) {
    setAddingId(datasetId);
    try {
      await addDatasets.mutateAsync({ collectionId, datasetIds: [datasetId] });
      toast.success(t('toasts.datasetAdded'));
      // The membership list is paginated, so it may not show the new member.
      setAddedIds((prev) => [...prev, datasetId]);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t('toasts.addError'),
      );
    } finally {
      setAddingId(null);
    }
  }

  // Filter out datasets already in the collection
  const available = results.filter((r) => !currentDatasetIds.includes(r.id) && !addedIds.includes(r.id));

  return (
    <div className="space-y-4">
      <h3 className="text-base font-semibold">{t('membership.title')}</h3>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSearch();
        }}
        className="flex gap-2"
      >
        <div className="relative flex-1">
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
        <Button type="submit" variant="outline" disabled={searching || !query.trim()}>
          {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : t('membership.searchButton')}
        </Button>
      </form>

      {/* Search results */}
      {available.length > 0 && (
        <div className="rounded-md border divide-y">
          {available.map((record) => (
            <div
              key={record.id}
              className="flex items-center justify-between gap-4 px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate">
                  {record.properties.title}
                </p>
                {record.properties.description && (
                  <p className="text-xs text-muted-foreground truncate mt-0.5">
                    {record.properties.description}
                  </p>
                )}
              </div>
              <Button
                variant="outline"
                size="sm"
                disabled={addingId === record.id}
                onClick={() => handleAdd(record.id)}
                aria-label={t('membership.addAria', { title: record.properties.title })}
                className="flex-shrink-0"
              >
                {addingId === record.id ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <>
                    <Plus className="h-4 w-4 me-1" />
                    {t('membership.addButton')}
                  </>
                )}
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* No results message */}
      {results.length > 0 && available.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-4">
          {t('membership.allAlreadyAdded')}
        </p>
      )}
    </div>
  );
}
