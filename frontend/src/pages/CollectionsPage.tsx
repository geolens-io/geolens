import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderOpen, Plus, Search } from 'lucide-react';
import { PageShell } from '@/components/layout/PageShell';
import { PageHeader } from '@/components/layout/PageHeader';
import { ErrorState } from '@/components/layout/ErrorState';
import { EmptyState } from '@/components/layout/EmptyState';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { CollectionCard } from '@/components/collections/CollectionCard';
import { CollectionCardSkeleton } from '@/components/collections/CollectionCardSkeleton';
import { CollectionCreateDialog } from '@/components/collections/CollectionCreateDialog';
import { Pagination } from '@/components/layout/Pagination';
import { useCollections } from '@/hooks/use-collections';
import { useAuthStore } from '@/stores/auth-store';
import { useDocumentTitle } from '@/hooks/use-document-title';

const PAGE_SIZE = 20;

export function CollectionsPage() {
  const [skip, setSkip] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<'updated_at' | 'created_at' | 'name'>('updated_at');
  const [createOpen, setCreateOpen] = useState(false);
  const { t } = useTranslation('collections');
  const { data, isLoading, error } = useCollections(0, 100);
  const isEditor = useAuthStore((s) => s.isEditor());
  const handlePageChange = useCallback((newOffset: number) => setSkip(newOffset), []);
  useDocumentTitle(t('common:pageTitle.collections'));

  const filtered = (data?.collections.filter((c) =>
    c.name.toLowerCase().includes(searchQuery.toLowerCase())
  ) ?? []).sort((a, b) => {
    if (sortBy === 'name') return a.name.localeCompare(b.name);
    const dateA = sortBy === 'created_at' ? a.created_at : a.updated_at;
    const dateB = sortBy === 'created_at' ? b.created_at : b.updated_at;
    return new Date(dateB).getTime() - new Date(dateA).getTime();
  });
  const totalFiltered = filtered.length;
  const paged = filtered.slice(skip, skip + PAGE_SIZE);

  return (
    <PageShell maxWidth="narrow">
      <PageHeader
        title={t('title')}
        actions={data || isEditor ? (
          <>
            {data ? <Badge variant="secondary">{searchQuery ? totalFiltered : data.total}</Badge> : undefined}
            {isEditor && (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4 me-1" />
                {t('newCollection')}
              </Button>
            )}
          </>
        ) : undefined}
      />

      {/* Browse toolbar */}
      {data && data.total > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder={t('search.placeholder')}
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setSkip(0); }}
              className="ps-9"
            />
          </div>
          <Select value={sortBy} onValueChange={(v) => { setSortBy(v as typeof sortBy); setSkip(0); }}>
            <SelectTrigger className="w-[160px]" aria-label={t('sort.label', { defaultValue: 'Sort by' })}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="updated_at">{t('sort.lastUpdated', { defaultValue: 'Last updated' })}</SelectItem>
              <SelectItem value="created_at">{t('sort.dateCreated', { defaultValue: 'Date created' })}</SelectItem>
              <SelectItem value="name">{t('sort.name', { defaultValue: 'Name' })}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div className="space-y-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <CollectionCardSkeleton key={i} />
          ))}
        </div>
      )}

      {/* Error state */}
      {error && (
        <ErrorState message={t('error.message', { error: error.message })} />
      )}

      {/* Empty state - no collections at all */}
      {data && data.total === 0 && (
        <EmptyState
          icon={FolderOpen}
          title={t('empty.title')}
          description={t('empty.description')}
          action={
            isEditor ? (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4 me-1" />
                {t('empty.cta')}
              </Button>
            ) : undefined
          }
        />
      )}

      {/* Empty search results */}
      {data && data.total > 0 && totalFiltered === 0 && (
        <EmptyState
          icon={Search}
          title={t('search.empty')}
          description={t('search.emptyHint')}
        />
      )}

      {/* Collection cards */}
      {data && paged.length > 0 && (
        <div className="space-y-4">
          {paged.map((collection) => (
            <CollectionCard key={collection.id} collection={collection} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {data && totalFiltered > PAGE_SIZE && (
        <Pagination
          total={totalFiltered}
          offset={skip}
          limit={PAGE_SIZE}
          onPageChange={handlePageChange}
        />
      )}

      {/* Create collection dialog */}
      <CollectionCreateDialog open={createOpen} onOpenChange={setCreateOpen} />
    </PageShell>
  );
}
