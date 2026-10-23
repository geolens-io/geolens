import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, X } from 'lucide-react';
import { useMyGroups, useSetDatasetGroups } from '@/components/dataset/hooks/use-dataset';
import { UserPicker, type PickerUser } from '@/components/admin/UserPicker';
import { Button } from '@/components/ui/button';
import { LiveAnnouncement } from '@/components/ui/live-announcement';
import { formatMutationError } from '@/lib/error-map';
import { getVisibilityLabel } from '@/i18n/labels';
import type { GroupRef } from '@/types/api';

interface DatasetGroupShareProps {
  datasetId: string;
  visibility: string;
  groups: GroupRef[];
}

/** Which sentence says what saving does to the audience at the current visibility. */
function effectKey(visibility: string, hadGroups: boolean, hasGroups: boolean) {
  if (visibility === 'private') return hasGroups ? 'effectToRestricted' : 'effectPrivateEmpty';
  if (visibility === 'restricted') return hasGroups || !hadGroups ? 'effectRestricted' : 'effectToPrivate';
  return 'effectKept';
}

export function DatasetGroupShare({ datasetId, visibility, groups: current }: DatasetGroupShareProps) {
  const { t } = useTranslation('dataset');
  const myGroups = useMyGroups(true);
  const save = useSetDatasetGroups();
  const pickerRef = useRef<HTMLInputElement>(null);
  // Null until the user edits; the server's list is the baseline after a refetch.
  const [draft, setDraft] = useState<GroupRef[] | null>(null);
  const [outcome, setOutcome] = useState({ text: '', n: 0 });

  const selected = draft ?? current;
  const selectedIds = useMemo(() => new Set(selected.map((g) => g.id)), [selected]);
  const candidates: PickerUser[] = useMemo(
    () =>
      (myGroups.data ?? [])
        .filter((g) => !selectedIds.has(g.id))
        .map((g) => ({ id: g.id, username: g.name })),
    [myGroups.data, selectedIds],
  );
  const dirty =
    selected.length !== current.length || selected.some((g) => !current.some((c) => c.id === g.id));

  function announce(text: string) {
    setOutcome((prev) => ({ text, n: prev.n + 1 }));
  }

  function edit(next: GroupRef[], message: string) {
    save.reset();
    setDraft(next);
    announce(message);
  }

  function handleAdd(picked: PickerUser) {
    edit([...selected, { id: picked.id, name: picked.username }], t('groupShare.added', { name: picked.username }));
  }

  function handleRemove(group: GroupRef) {
    edit(
      selected.filter((g) => g.id !== group.id),
      t('groupShare.removed', { name: group.name }),
    );
    pickerRef.current?.focus();
  }

  function handleSave() {
    save.mutate(
      { datasetId, groupIds: selected.map((g) => g.id) },
      {
        onSuccess: (result) => {
          setDraft(null);
          announce(t('groupShare.saved', { visibility: getVisibilityLabel(t, result.visibility) }));
          pickerRef.current?.focus();
        },
      },
    );
  }

  const effect = t(`groupShare.${effectKey(visibility, current.length > 0, selected.length > 0)}`, {
    visibility: getVisibilityLabel(t, visibility),
  });

  return (
    <section className="mt-6 border-t pt-4" aria-labelledby="dataset-group-share">
      <h3 id="dataset-group-share" className="text-sm font-medium">
        {t('groupShare.title')}
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">{t('groupShare.help')}</p>

      <ul aria-label={t('groupShare.selectedLabel')} className="mt-3 flex flex-wrap gap-2">
        {selected.map((group) => (
          <li
            key={group.id}
            className="inline-flex items-center gap-1 rounded-md border bg-muted/40 py-0.5 ps-2 pe-0.5 text-sm"
          >
            <span>{group.name}</span>
            <Button
              variant="ghost"
              size="icon-xs"
              disabled={save.isPending}
              aria-label={t('groupShare.remove', { name: group.name })}
              onClick={() => handleRemove(group)}
            >
              <X className="size-3.5" aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ul>
      {selected.length === 0 && (
        <p className="mt-3 text-sm text-muted-foreground">{t('groupShare.none')}</p>
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
            ref={pickerRef}
            label={t('groupShare.pickerLabel')}
            users={candidates}
            onSelect={handleAdd}
            busy={save.isPending}
            text={{
              placeholder: t('groupShare.placeholder'),
              noMatches: t('groupShare.noMatches'),
              results: (count) => t('groupShare.results', { count }),
            }}
          />
        )}
      </div>

      <p className="mt-3 text-xs text-muted-foreground">{effect}</p>
      {save.error && (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {formatMutationError('dataset:groupShare.failed', save.error)}
        </p>
      )}
      <Button className="mt-3" size="sm" disabled={!dirty || save.isPending} onClick={handleSave}>
        {save.isPending ? t('metadataEdit.saving') : t('groupShare.save')}
      </Button>
      <LiveAnnouncement text={outcome.text} trigger={String(outcome.n)} />
    </section>
  );
}
