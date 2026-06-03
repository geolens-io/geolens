import { useState, useEffect, useCallback } from 'react';
import { Map as MapIcon, Plus, Search, LayoutList, LayoutGrid } from 'lucide-react';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
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
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { TooltipProvider } from '@/components/ui/tooltip';
import { MapCard } from '@/components/maps/MapCard';
import { MapCardGrid } from '@/components/maps/MapCardGrid';
import { MapCardSkeleton } from '@/components/maps/MapCardSkeleton';
import { MapCreateDialog } from '@/components/maps/MapCreateDialog';
import { MapDeleteDialog } from '@/components/maps/MapDeleteDialog';
import { Pagination } from '@/components/layout/Pagination';
import { useMaps, useDeleteMap } from '@/hooks/use-maps';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useAuthStore } from '@/stores/auth-store';

const PAGE_SIZE = 20;
const VIEW_STORAGE_KEY = 'geolens-maps-view';

function getStoredView(): string {
  try {
    return localStorage.getItem(VIEW_STORAGE_KEY) ?? 'list';
  } catch {
    return 'list';
  }
}

export function MapsPage() {
  const { t } = useTranslation();
  const isEditor = useAuthStore((s) => s.isEditor());
  const [skip, setSkip] = useState(0);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [sortBy, setSortBy] = useState('updated_at');
  const [sortDir, setSortDir] = useState('desc');
  const [visibility, setVisibility] = useState('all');
  const [viewMode, setViewMode] = useState(getStoredView);
  const [createOpen, setCreateOpen] = useState(false);
  const [deletingMap, setDeletingMap] = useState<{ id: string; name: string } | null>(null);
  const handlePageChange = useCallback((newOffset: number) => setSkip(newOffset), []);
  useDocumentTitle(t('common:pageTitle.maps'));

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Reset pagination when filters change
  useEffect(() => {
    setSkip(0);
  }, [debouncedSearch, sortBy, sortDir, visibility]);

  const { data, isLoading, error } = useMaps({
    skip,
    limit: PAGE_SIZE,
    search: debouncedSearch || undefined,
    sort_by: sortBy,
    sort_dir: sortDir,
    visibility: visibility === 'all' ? undefined : visibility,
  });
  const deleteMap = useDeleteMap();

  function handleSortChange(value: string) {
    setSortBy(value);
    setSortDir(value === 'name' ? 'asc' : 'desc');
  }

  function handleViewChange(value: string) {
    if (!value) return; // ToggleGroup sends empty string on deselect
    setViewMode(value);
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, value);
    } catch {
      // localStorage not available
    }
  }

  function handleDeleteConfirm() {
    if (!deletingMap) return;
    deleteMap.mutate(deletingMap.id, {
      onSuccess: () => {
        toast.success(t('maps.deleted'));
        setDeletingMap(null);
      },
      onError: () => {
        toast.error(t('maps.deleteFailed'));
      },
    });
  }

  function handleDeleteClick(id: string) {
    const map = data?.maps.find((m) => m.id === id);
    if (map) setDeletingMap({ id: map.id, name: map.name });
  }

  return (
    <TooltipProvider>
    <PageShell maxWidth="narrow">
      <PageHeader
        title={t('maps.title')}
        actions={
          <div className="flex items-center gap-2">
            {data && <Badge variant="secondary">{data.total}</Badge>}
            {isEditor && (
              <Button size="sm" onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4 me-1" />
                {t('maps.createMap', 'Create Map')}
              </Button>
            )}
          </div>
        }
      />

      {/* Browse toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-64">
          <Search className="absolute start-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder={t('maps.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="ps-9"
          />
        </div>

        <Select value={sortBy} onValueChange={handleSortChange}>
          <SelectTrigger
            className="w-[160px]"
            aria-label={t('maps.sortBy')}
          >
            <SelectValue placeholder={t('maps.sortBy')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="updated_at">{t('maps.lastUpdated')}</SelectItem>
            <SelectItem value="created_at">{t('maps.dateCreated')}</SelectItem>
            <SelectItem value="name">{t('maps.name')}</SelectItem>
          </SelectContent>
        </Select>

        {isEditor && (
          <Select value={visibility} onValueChange={setVisibility}>
            <SelectTrigger
              className="w-[140px]"
              aria-label={t('maps.visibility')}
            >
              <SelectValue placeholder={t('maps.visibility')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('maps.allMaps')}</SelectItem>
              <SelectItem value="private">{t('maps.private')}</SelectItem>
              <SelectItem value="internal">{t('maps.internal')}</SelectItem>
              <SelectItem value="public">{t('maps.public')}</SelectItem>
            </SelectContent>
          </Select>
        )}

        <ToggleGroup
          type="single"
          value={viewMode}
          onValueChange={handleViewChange}
          className="ms-auto"
        >
          <ToggleGroupItem value="list" aria-label={t('maps.listView')}>
            <LayoutList className="h-4 w-4" />
          </ToggleGroupItem>
          <ToggleGroupItem value="grid" aria-label={t('maps.gridView')}>
            <LayoutGrid className="h-4 w-4" />
          </ToggleGroupItem>
        </ToggleGroup>
      </div>

      {isLoading && (
        <div className="space-y-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <MapCardSkeleton key={i} />
          ))}
        </div>
      )}

      {error && (
        <ErrorState message={t('maps.loadFailed', { message: error.message })} />
      )}

      {data && data.total === 0 && (
        <EmptyState
          icon={MapIcon}
          title={t('maps.noMapsYet')}
          description={
            debouncedSearch || visibility !== 'all'
              ? t('maps.noMapsMatch')
              : t('maps.noMapsDescription')
          }
          action={
            !debouncedSearch && visibility === 'all' && isEditor ? (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4 me-1" />
                {t('maps.createFirstMap')}
              </Button>
            ) : undefined
          }
        />
      )}

      {data && data.maps.length > 0 && viewMode === 'list' && (
        <div className="space-y-4">
          {data.maps.map((map) => (
            <MapCard key={map.id} map={map} onDelete={isEditor ? handleDeleteClick : undefined} />
          ))}
        </div>
      )}

      {data && data.maps.length > 0 && viewMode === 'grid' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.maps.map((map) => (
            <MapCardGrid key={map.id} map={map} onDelete={isEditor ? handleDeleteClick : undefined} />
          ))}
        </div>
      )}

      {data && data.total > 0 && (
        <Pagination
          total={data.total}
          offset={skip}
          limit={PAGE_SIZE}
          onPageChange={handlePageChange}
        />
      )}

      {isEditor && (
        <>
          <MapCreateDialog open={createOpen} onOpenChange={setCreateOpen} />

          <MapDeleteDialog
            open={!!deletingMap}
            onOpenChange={(open) => !open && setDeletingMap(null)}
            mapName={deletingMap?.name ?? ''}
            onConfirm={handleDeleteConfirm}
            isDeleting={deleteMap.isPending}
          />
        </>
      )}
    </PageShell>
    </TooltipProvider>
  );
}
