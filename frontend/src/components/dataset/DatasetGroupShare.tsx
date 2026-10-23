import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useSetDatasetGroups } from '@/components/dataset/hooks/use-dataset';
import { GroupPicker } from '@/components/groups/GroupPicker';
import { Button } from '@/components/ui/button';
import { LiveAnnouncement } from '@/components/ui/live-announcement';
import { groupEffectKey, useGroupDraft } from '@/hooks/use-group-draft';
import { formatMutationError } from '@/lib/error-map';
import { getVisibilityLabel } from '@/i18n/labels';
import type { GroupRef } from '@/types/api';

interface DatasetGroupShareProps {
  datasetId: string;
  visibility: string;
  groups: GroupRef[];
}

export function DatasetGroupShare({ datasetId, visibility, groups: current }: DatasetGroupShareProps) {
  const { t } = useTranslation('dataset');
  const save = useSetDatasetGroups();
  const pickerRef = useRef<HTMLInputElement>(null);
  const { selected, dirty, edit, reset, announcement, announce } = useGroupDraft(current);

  function handleSave() {
    save.mutate(
      { datasetId, groupIds: selected.map((g) => g.id) },
      {
        onSuccess: (result) => {
          reset();
          announce(t('groupShare.saved', { visibility: getVisibilityLabel(t, result.visibility) }));
          if (result.metadata_warnings?.length) toast.warning(result.metadata_warnings[0]);
          pickerRef.current?.focus();
        },
      },
    );
  }

  const effect = t(`groupShare.${groupEffectKey(visibility, current.length > 0, selected.length > 0)}`, {
    visibility: getVisibilityLabel(t, visibility),
  });

  return (
    <section className="mt-6 border-t pt-4" aria-labelledby="dataset-group-share">
      <h3 id="dataset-group-share" className="text-sm font-medium">
        {t('groupShare.title')}
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">{t('groupShare.help')}</p>

      <div className="mt-3">
        <GroupPicker
          selected={selected}
          onChange={(next) => {
            save.reset();
            edit(next);
          }}
          onAnnounce={announce}
          busy={save.isPending}
          inputRef={pickerRef}
        />
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
      <LiveAnnouncement text={announcement.text} trigger={String(announcement.n)} />
    </section>
  );
}
