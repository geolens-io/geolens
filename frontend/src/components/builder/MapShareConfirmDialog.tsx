import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import type { MapGroupsConfirm, MapLayerAccessGap } from '@/types/api';

interface MapShareConfirmDialogProps {
  layers: MapLayerAccessGap[];
  groupNames: ReadonlyMap<string, string>;
  pending: boolean;
  /** Why the confirmed request was refused, when it was. */
  error?: string | null;
  onConfirm: (confirm: MapGroupsConfirm) => void;
  onCancel: () => void;
  /** Where focus goes once the dialog is gone. */
  onCloseFocus: () => void;
}

/**
 * Asks what to do about layers some of the chosen groups can't read before the
 * map is shared. Open whenever `layers` is non-empty; Cancel and Escape send
 * nothing, and the cancel button takes the initial focus.
 */
export function MapShareConfirmDialog({
  layers,
  groupNames,
  pending,
  error,
  onConfirm,
  onCancel,
  onCloseFocus,
}: MapShareConfirmDialogProps) {
  const { t } = useTranslation('builder');
  const someUnshareable = layers.some((layer) => !layer.can_share);

  return (
    <AlertDialog open onOpenChange={(open) => !open && !pending && onCancel()}>
      <AlertDialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          onCloseFocus();
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>{t('share.groups.confirm.title')}</AlertDialogTitle>
          <AlertDialogDescription>{t('share.groups.confirm.description')}</AlertDialogDescription>
        </AlertDialogHeader>

        <ul className="max-h-60 space-y-2 overflow-auto text-sm">
          {layers.map((layer) => (
            <li key={layer.layer_id} className="rounded-md border px-3 py-2">
              <p className="font-medium">
                {layer.layer_title === layer.dataset_title
                  ? layer.layer_title
                  : t('share.groups.confirm.layer', { layer: layer.layer_title, dataset: layer.dataset_title })}
              </p>
              <p className="text-xs text-muted-foreground">
                {t('share.groups.confirm.lacking', {
                  groups: layer.group_ids.map((id) => groupNames.get(id) ?? id).join(', '),
                })}
              </p>
              <p className="text-xs text-muted-foreground">
                {t(layer.can_share ? 'share.groups.confirm.canShare' : 'share.groups.confirm.cannotShare')}
              </p>
            </li>
          ))}
        </ul>
        {someUnshareable && (
          <p className="text-xs text-muted-foreground">
            {t('share.groups.confirm.someStayHidden')}
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{t('common:cancel')}</AlertDialogCancel>
          <Button variant="outline" disabled={pending} onClick={() => onConfirm('map_only')}>
            {t('share.groups.confirm.mapOnly')}
          </Button>
          <Button disabled={pending} onClick={() => onConfirm('share_datasets')}>
            {t('share.groups.confirm.shareDatasets')}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
