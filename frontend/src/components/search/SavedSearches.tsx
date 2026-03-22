import { useState } from 'react';
import { Bookmark, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  useSavedSearches,
  useSaveSearch,
  useDeleteSavedSearch,
} from '@/hooks/use-saved-searches';
import { useSearchStore } from '@/stores/search-store';

/**
 * Save Search button with dialog — intended for use inside FilterPanel toolbar.
 */
export function SaveSearchButton() {
  const { t } = useTranslation('search');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [searchName, setSearchName] = useState('');
  const saveSearch = useSaveSearch();

  const handleSave = () => {
    if (!searchName.trim()) return;
    const params = useSearchStore.getState().toParams();
    saveSearch.mutate(
      { name: searchName.trim(), params },
      {
        onSuccess: () => {
          setSearchName('');
          setDialogOpen(false);
        },
      },
    );
  };

  return (
    <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="shrink-0">
          <Bookmark className="size-4" />
          <span className="hidden sm:inline">{t('savedSearches.saveButton')}</span>
          <span className="sm:hidden">
            {t('savedSearches.saveShort', { defaultValue: 'Save' })}
          </span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('savedSearches.dialogTitle')}</DialogTitle>
          <DialogDescription>
            {t('savedSearches.dialogDescription')}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Input
            placeholder={t('savedSearches.namePlaceholder')}
            value={searchName}
            onChange={(e) => setSearchName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSave();
            }}
            // eslint-disable-next-line jsx-a11y/no-autofocus -- intentional: dialog just opened for naming a saved search
            autoFocus
          />
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                {t('common:cancel')}
              </Button>
            </DialogClose>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!searchName.trim() || saveSearch.isPending}
            >
              {saveSearch.isPending ? t('savedSearches.saving') : t('common:save')}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Saved search chips — lightweight horizontal row of quick-access shortcuts.
 * Renders nothing when there are no saved searches or still loading.
 */
export function SavedSearches() {
  const { t } = useTranslation('search');

  const { data, isLoading } = useSavedSearches();
  const deleteSearch = useDeleteSavedSearch();
  const restoreParams = useSearchStore((s) => s.restoreParams);

  const searches = data?.searches ?? [];

  const handleLoad = (params: Record<string, string>) => {
    restoreParams(params);
  };

  const handleDelete = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    deleteSearch.mutate(id);
  };

  if (isLoading || searches.length === 0) return null;

  return (
    <div
      className="flex items-center gap-1.5 overflow-x-auto"
      aria-label={t('savedSearches.savedSearchesLabel', {
        defaultValue: 'Saved searches',
      })}
    >
      {searches.map((search) => (
        <div
          key={search.id}
          className="group inline-flex shrink-0 items-center gap-1 rounded-full border bg-secondary/50 py-1 pl-2.5 pr-1 text-xs font-medium text-secondary-foreground"
        >
          <button
            type="button"
            onClick={() => handleLoad(search.params)}
            className="truncate text-left transition-colors hover:text-foreground"
          >
            {search.name}
          </button>
          <button
            type="button"
            aria-label={t('savedSearches.removeSavedSearch', {
              defaultValue: 'Remove saved search',
            })}
            onClick={(e) => handleDelete(e, search.id)}
            className="rounded-full p-0.5 opacity-60 transition-colors hover:bg-destructive/20 hover:opacity-100"
          >
            <X className="size-3" />
          </button>
        </div>
      ))}
    </div>
  );
}
