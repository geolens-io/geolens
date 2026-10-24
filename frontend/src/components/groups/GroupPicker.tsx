import { useEffect, useMemo, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, X } from 'lucide-react';
import { useMyGroups } from '@/hooks/use-groups';
import { UserPicker, type PickerUser } from '@/components/admin/UserPicker';
import { Button } from '@/components/ui/button';
import { formatMutationError } from '@/lib/error-map';
import type { GroupRef } from '@/types/api';

interface GroupPickerProps {
  selected: GroupRef[];
  onChange: (next: GroupRef[]) => void;
  /** Receives the sentence to read out after an add or a removal. */
  onAnnounce: (text: string) => void;
  /** Ignores picks and removals while a save is in flight. */
  busy?: boolean;
  inputRef?: RefObject<HTMLInputElement | null>;
  /** Focuses the search input once the caller's groups have loaded. */
  focusWhenReady?: boolean;
  /** Reports the results list opening and closing, so a dialog can leave Escape to it. */
  onOpenChange?: (open: boolean) => void;
}

/**
 * Chips for the groups a dataset or map is shared with, plus a searchable
 * picker over the caller's own groups (every group for an admin).
 */
export function GroupPicker({ selected, onChange, onAnnounce, busy, inputRef, focusWhenReady, onOpenChange }: GroupPickerProps) {
  const { t } = useTranslation('dataset');
  const myGroups = useMyGroups(true);
  const ready = !myGroups.isLoading;

  useEffect(() => {
    if (focusWhenReady && ready) inputRef?.current?.focus();
  }, [focusWhenReady, ready, inputRef]);

  const selectedIds = useMemo(() => new Set(selected.map((g) => g.id)), [selected]);
  const candidates: PickerUser[] = useMemo(
    () =>
      (myGroups.data ?? [])
        .filter((g) => !selectedIds.has(g.id))
        .map((g) => ({ id: g.id, username: g.name })),
    [myGroups.data, selectedIds],
  );

  function change(next: GroupRef[], message: string) {
    onChange(next);
    onAnnounce(message);
  }

  function handleAdd(picked: PickerUser) {
    change(
      [...selected, { id: picked.id, name: picked.username }],
      t('groupShare.added', { name: picked.username }),
    );
  }

  function handleRemove(group: GroupRef) {
    change(
      selected.filter((g) => g.id !== group.id),
      t('groupShare.removed', { name: group.name }),
    );
    inputRef?.current?.focus();
  }

  return (
    <div>
      <ul aria-label={t('groupShare.selectedLabel')} className="flex flex-wrap gap-2">
        {selected.map((group) => (
          <li
            key={group.id}
            className="inline-flex items-center gap-1 rounded-md border bg-muted/40 py-0.5 ps-2 pe-0.5 text-sm"
          >
            <span>{group.name}</span>
            <Button
              variant="ghost"
              size="icon-xs"
              disabled={busy}
              aria-label={t('groupShare.remove', { name: group.name })}
              onClick={() => handleRemove(group)}
            >
              <X className="size-3.5" aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ul>
      {selected.length === 0 && (
        <p className="text-sm text-muted-foreground">{t('groupShare.none')}</p>
      )}

      <div className="mt-3 max-w-sm">
        {myGroups.isLoading ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" /> {t('common:loading')}
          </p>
        ) : myGroups.error ? (
          <p role="alert" className="text-sm text-destructive">
            {formatMutationError('dataset:groupShare.loadFailed', myGroups.error)}
          </p>
        ) : (myGroups.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('groupShare.noGroupsAvailable')}</p>
        ) : (
          <UserPicker
            ref={inputRef}
            label={t('groupShare.pickerLabel')}
            users={candidates}
            onSelect={handleAdd}
            busy={busy}
            onOpenChange={onOpenChange}
            text={{
              placeholder: t('groupShare.placeholder'),
              noMatches: t('groupShare.noMatches'),
              results: (count) => t('groupShare.results', { count }),
            }}
          />
        )}
      </div>
    </div>
  );
}
