import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AlertTriangle } from 'lucide-react';
import { useMapAudienceBusy, useSetMapGroups } from '@/hooks/use-maps';
import { GroupPicker } from '@/components/groups/GroupPicker';
import { MapShareConfirmDialog } from '@/components/builder/MapShareConfirmDialog';
import { layersHiddenFromGroups } from '@/api/maps';
import { Button } from '@/components/ui/button';
import { LiveAnnouncement } from '@/components/ui/live-announcement';
import { groupEffectKey, useGroupDraft } from '@/hooks/use-group-draft';
import { formatMutationError } from '@/lib/error-map';
import type { GroupRef, MapGroupsConfirm, MapGroupsResponse, MapLayerAccessGap } from '@/types/api';

interface MapGroupShareProps {
  mapId: string;
  visibility: string;
  groups: GroupRef[];
  /** The map has a share link or embed token, which sharing with groups revokes. */
  hasLinks: boolean;
  /** Moves focus to the picker once it is ready, after the owner chose "Specific groups". */
  focusOnOpen?: boolean;
  /** Called with the visibility the server reports after a save. */
  onSaved?: (visibility: string) => void;
  /** Reports the group picker's results list opening and closing. */
  onPickerOpenChange?: (open: boolean) => void;
}

const SAVED_KEYS: Record<string, string> = {
  restricted: 'share.groups.savedRestricted',
  private: 'share.groups.savedPrivate',
};

export function MapGroupShare({
  mapId, visibility, groups: current, hasLinks, focusOnOpen, onSaved, onPickerOpenChange,
}: MapGroupShareProps) {
  const { t } = useTranslation('builder');
  const save = useSetMapGroups();
  const audienceBusy = useMapAudienceBusy();
  // Unmounting with the list open would otherwise leave the dialog's Escape blocked.
  useEffect(() => () => onPickerOpenChange?.(false), [onPickerOpenChange]);
  const pickerRef = useRef<HTMLInputElement>(null);
  const { selected, dirty, edit, reset, announcement, announce } = useGroupDraft(current);
  const becomesRestricted = visibility === 'private' && selected.length > 0;

  // The layers the server says some chosen group can't read. While set, the
  // confirmation is open and nothing has been saved.
  const [gap, setGap] = useState<MapLayerAccessGap[] | null>(null);

  function announceSaved(result: MapGroupsResponse) {
    const shared = result.shared_dataset_ids?.length ?? 0;
    const hidden = result.hidden_layers?.length ?? 0;
    if (shared === 0 && hidden === 0) {
      announce(t(SAVED_KEYS[result.visibility] ?? 'share.groups.saved'));
      return;
    }
    // The toast's own live region reads this out, so it isn't announced twice.
    toast.success(
      [
        shared > 0
          ? t('share.groups.confirm.sharedDatasets', { count: shared })
          : t('share.groups.confirm.mapShared'),
        hidden > 0 ? t('share.groups.confirm.hiddenLayers', { count: hidden }) : '',
      ]
        .filter(Boolean)
        .join(' '),
    );
  }

  function submit(confirm?: MapGroupsConfirm) {
    save.mutate(
      { mapId, groupIds: selected.map((g) => g.id), confirm },
      {
        onSuccess: (result) => {
          reset();
          setGap(null);
          announceSaved(result);
          pickerRef.current?.focus();
          onSaved?.(result.visibility);
        },
        // A refusal after the confirmation keeps the dialog open to show why.
        onError: (err) => {
          const layers = layersHiddenFromGroups(err);
          if (layers) setGap(layers);
        },
      },
    );
  }

  // The 409 asking for confirmation is not a failure; anything else is.
  const errorText =
    save.error && !layersHiddenFromGroups(save.error)
      ? formatMutationError('builder:share.groups.failed', save.error)
      : null;

  function cancelConfirm() {
    setGap(null);
    save.reset();
  }

  return (
    <section className="space-y-3 border-t pt-4" aria-labelledby="map-group-share">
      <div>
        <h3 id="map-group-share" className="text-sm font-semibold">
          {t('share.groups.title')}
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">{t('share.groups.help')}</p>
      </div>

      <GroupPicker
        selected={selected}
        onChange={(next) => {
          save.reset();
          edit(next);
        }}
        onAnnounce={announce}
        busy={audienceBusy}
        inputRef={pickerRef}
        focusWhenReady={focusOnOpen}
        onOpenChange={onPickerOpenChange}
      />

      <p className="text-xs text-muted-foreground">
        {t(`share.groups.${groupEffectKey(visibility, current.length > 0, selected.length > 0)}`)}
      </p>
      {becomesRestricted && hasLinks && (
        <p className="flex items-start gap-2 text-xs text-foreground">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden="true" />
          {t('share.groups.linksRevoked')}
        </p>
      )}
      {errorText && !gap && (
        <p role="alert" className="text-sm text-destructive">
          {errorText}
        </p>
      )}
      <Button size="sm" disabled={!dirty || audienceBusy} onClick={() => submit()}>
        {save.isPending ? t('share.updatingVisibility') : t('share.groups.save')}
      </Button>
      {gap && (
        <MapShareConfirmDialog
          layers={gap}
          groupNames={new Map([...current, ...selected].map((g) => [g.id, g.name]))}
          pending={save.isPending}
          error={errorText}
          onConfirm={submit}
          onCancel={cancelConfirm}
          onCloseFocus={() => pickerRef.current?.focus()}
        />
      )}
      <LiveAnnouncement
        text={focusOnOpen && announcement.n === 0 ? t('share.groups.openedHint') : announcement.text}
        trigger={String(announcement.n)}
      />
    </section>
  );
}
