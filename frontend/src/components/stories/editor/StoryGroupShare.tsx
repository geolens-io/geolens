import { useEffect, useId, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  reportStoryWriteError,
  setStoryGroups,
  sharingMapsClears,
  type MapsBlockingStory,
  type ShareBlockingMaps,
} from '@/api/stories';
import { GroupPicker } from '@/components/groups/GroupPicker';
import { Button } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { LiveAnnouncement } from '@/components/ui/live-announcement';
import { groupEffectKey, useGroupDraft } from '@/hooks/use-group-draft';
import type { GroupRef, StoryGroupsResponse } from '@/types/api';
import { BlockingMapsList, blockedDescriptionKey } from './BlockingMapsList';
import { captureAccount } from './same-account';

const SAVED_KEYS: Record<string, string> = {
  restricted: 'groups.savedRestricted',
  private: 'groups.savedPrivate',
};

interface StoryGroupShareProps {
  storyId: string;
  visibility: string;
  groups: GroupRef[];
  onSaved: (result: StoryGroupsResponse) => void;
  /** Reports the group picker's results list opening and closing. */
  onPickerOpenChange?: (open: boolean) => void;
}

/**
 * The groups a story is shared with. Saving applies at once. When maps the
 * published story uses block some chosen group, nothing is saved until the
 * author confirms sharing their own blocking maps with those groups.
 */
export function StoryGroupShare({ storyId, visibility, groups: current, onSaved, onPickerOpenChange }: StoryGroupShareProps) {
  const { t } = useTranslation('stories');
  const headingId = useId();
  const pickerRef = useRef<HTMLInputElement>(null);
  // Unmounting with the list open would otherwise leave the dialog's Escape blocked.
  useEffect(() => () => onPickerOpenChange?.(false), [onPickerOpenChange]);
  const { selected, dirty, edit, reset, announcement, announce } = useGroupDraft(current);
  const [blocked, setBlocked] = useState<MapsBlockingStory | null>(null);
  const save = useMutation({
    mutationFn: (confirm?: ShareBlockingMaps) =>
      setStoryGroups(
        storyId,
        selected.map((g) => g.id),
        confirm,
      ),
  });

  async function submit(confirm?: ShareBlockingMaps) {
    const same = captureAccount();
    try {
      const result = await save.mutateAsync(confirm);
      if (!same()) return;
      reset();
      setBlocked(null);
      onSaved(result);
      const shared = result.shared_map_ids?.length ?? 0;
      announce(
        shared > 0
          ? t('groups.sharedMaps', { count: shared })
          : t(SAVED_KEYS[result.visibility] ?? 'groups.saved'),
      );
      pickerRef.current?.focus();
    } catch (err) {
      if (!same()) return;
      reportStoryWriteError(err, 'stories:groups.failed', (conflict) => {
        if (conflict.code === 'maps_narrower_than_story') setBlocked(conflict);
      });
    }
  }

  const canShareMaps = blocked !== null && sharingMapsClears(blocked);

  return (
    <section aria-labelledby={headingId} className="space-y-2">
      <div>
        <h3 id={headingId} className="text-sm font-medium">
          {t('groups.heading')}
        </h3>
        <p className="text-xs text-muted-foreground">{t('groups.help')}</p>
      </div>
      <GroupPicker
        selected={selected}
        onChange={(next) => {
          setBlocked(null);
          edit(next);
        }}
        onAnnounce={announce}
        busy={save.isPending}
        inputRef={pickerRef}
        onOpenChange={onPickerOpenChange}
      />
      <p className="text-xs text-muted-foreground">
        {t(`groups.${groupEffectKey(visibility, current.length > 0, selected.length > 0)}`)}
      </p>
      <Button type="button" size="sm" variant="outline" disabled={!dirty || save.isPending} onClick={() => void submit()}>
        {save.isPending ? t('groups.saving') : t('groups.save')}
      </Button>
      <ConfirmDialog
        open={blocked !== null}
        onOpenChange={(open) => !open && setBlocked(null)}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          pickerRef.current?.focus();
        }}
        title={t('groups.blockedTitle')}
        description={t(blockedDescriptionKey(true, canShareMaps))}
        confirm={
          canShareMaps
            ? { label: t('groups.shareMaps'), onClick: () => void submit('share_maps'), pending: save.isPending }
            : undefined
        }
      >
        {blocked && (
          <div className="space-y-2 text-sm">
            <BlockingMapsList maps={blocked.maps} unreadableMaps={blocked.unreadableMaps} sharing />
            {canShareMaps && <p className="text-muted-foreground">{t('groups.sharingRevokesLinks')}</p>}
          </div>
        )}
      </ConfirmDialog>
      <LiveAnnouncement text={announcement.text} trigger={String(announcement.n)} />
    </section>
  );
}
