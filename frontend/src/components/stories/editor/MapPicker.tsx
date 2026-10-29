import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { UserPicker, type PickerUser } from '@/components/admin/UserPicker';
import { VisibilityBadge } from '@/components/maps/VisibilityBadge';
import { Button } from '@/components/ui/button';
import { useDebouncedValue } from '@/hooks/use-debounce';
import { useMapSearch } from '@/hooks/use-maps';
import { queryKeys } from '@/lib/query-keys';

const NO_MAP = '';

interface MapPickerProps {
  /** The chosen map's name, or null for a text-only chapter. */
  currentName: string | null;
  disabled?: boolean;
  onChoose: (mapId: string | null) => void;
}

/**
 * A combobox over every map the author can read, searched on the server and
 * loaded a page at a time; "No map" makes the chapter text-only.
 */
export function MapPicker({ currentName, disabled, onChoose }: MapPickerProps) {
  const { t } = useTranslation('stories');
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const search = useDebouncedValue(query.trim(), 300);
  const maps = useMapSearch(search, open);

  const visibility = useMemo(() => {
    const byId = new Map<string, string>();
    for (const page of maps.data?.pages ?? []) for (const map of page.maps) byId.set(map.id, map.visibility);
    return byId;
  }, [maps.data]);
  const options = useMemo<PickerUser[]>(
    () => [
      { id: NO_MAP, username: t('editor.scene.noMap') },
      ...(maps.data?.pages ?? []).flatMap((page) => page.maps.map((map) => ({ id: map.id, username: map.name }))),
    ],
    [maps.data, t],
  );
  const renderOption = useCallback(
    (option: PickerUser) =>
      option.id === NO_MAP ? (
        option.username
      ) : (
        <span className="flex items-center justify-between gap-2">
          <span className="truncate">{option.username}</span>
          <VisibilityBadge visibility={visibility.get(option.id) ?? 'private'} />
        </span>
      ),
    [visibility],
  );

  // Reopening starts from the first page rather than every page loaded before.
  // Removed once the list has closed and stopped observing the query.
  useEffect(() => {
    if (!open) qc.removeQueries({ queryKey: queryKeys.maps.picker(search) });
  }, [open, qc, search]);

  const loadMore = maps.hasNextPage && !maps.isFetchingNextPage ? () => void maps.fetchNextPage() : undefined;

  return (
    <div className="space-y-1">
      <p className="text-sm">
        {currentName ? t('editor.scene.currentMapIs', { name: currentName }) : t('editor.scene.noMap')}
      </p>
      <UserPicker
        label={t('editor.scene.map')}
        users={options}
        disabled={disabled}
        onSelect={(option) => onChoose(option.id === NO_MAP ? null : option.id)}
        onOpenChange={setOpen}
        onQueryChange={setQuery}
        onReachEnd={loadMore}
        renderOption={renderOption}
        text={{
          placeholder: t('editor.scene.searchMaps'),
          noMatches: t('editor.scene.noMapsFound'),
          // The count leaves out the No map option.
          results: (count) => t('editor.scene.mapResultsCount', { count: count - 1 }),
        }}
        footer={
          loadMore && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="mt-1 w-full"
              // Keeps focus in the search field, as the options do.
              onMouseDown={(event) => event.preventDefault()}
              onClick={loadMore}
            >
              {t('editor.scene.moreMaps')}
            </Button>
          )
        }
      />
    </div>
  );
}
