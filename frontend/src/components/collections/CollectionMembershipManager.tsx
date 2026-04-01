import { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Plus, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { searchDatasets } from '@/api/search';
import { useAbortSignal } from '@/hooks/use-abort-signal';
import { useAddDatasetsToCollection, useCollectionDatasets } from '@/hooks/use-collections';
import type { OGCRecordResponse } from '@/types/api';

interface CollectionMembershipManagerProps {
  collectionId: string;
}

export function CollectionMembershipManager({
  collectionId,
}: CollectionMembershipManagerProps) {
  const { t } = useTranslation('collections');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<OGCRecordResponse[]>([]);
  const [searching, setSearching] = useState(false);
  const [addingId, setAddingId] = useState<string | null>(null);
  const addDatasets = useAddDatasetsToCollection();
  const { data: datasetsData } = useCollectionDatasets(collectionId, 0, 200);
  const currentDatasetIds = datasetsData?.datasets.map((d) => d.id) ?? [];
  const abortRef = useRef<AbortController | null>(null);
  const unmountSignal = useAbortSignal();

  async function handleSearch() {
    const q = query.trim();
    if (!q) return;

    // Abort any in-flight search (superseding)
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Abort on unmount: listen for unmount signal and forward to per-request controller
    const onUnmount = () => controller.abort();
    unmountSignal.addEventListener('abort', onUnmount);

    setSearching(true);
    try {
      const data = await searchDatasets({ q, limit: '10' }, { signal: controller.signal });
      if (!controller.signal.aborted) {
        setResults(data.features);
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setResults([]);
      }
      // Suppress abort errors
      if (err instanceof DOMException && err.name === 'AbortError') return;
    } finally {
      unmountSignal.removeEventListener('abort', onUnmount);
      if (!controller.signal.aborted) {
        setSearching(false);
      }
    }
  }

  async function handleAdd(datasetId: string) {
    setAddingId(datasetId);
    try {
      await addDatasets.mutateAsync({ collectionId, datasetIds: [datasetId] });
      toast.success(t('toasts.datasetAdded'));
      // Remove from results since it's now in the collection
      setResults((prev) => prev.filter((r) => r.id !== datasetId));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t('toasts.addError'),
      );
    } finally {
      setAddingId(null);
    }
  }

  // Filter out datasets already in the collection
  const available = results.filter((r) => !currentDatasetIds.includes(r.id));

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
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
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
