import { useTranslation, Trans } from 'react-i18next';
import { Link } from 'react-router';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { useMapStories } from '@/hooks/use-maps';

interface MapDeleteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mapId: string | undefined;
  mapName: string;
  onConfirm: () => void;
  isDeleting: boolean;
}

export function MapDeleteDialog({
  open,
  onOpenChange,
  mapId,
  mapName,
  onConfirm,
  isDeleting,
}: MapDeleteDialogProps) {
  const { t } = useTranslation('builder');
  const { data: usage, isError, isFetching, refetch } = useMapStories(mapId, { enabled: open });
  // A cached answer may be out of date while the dialog asks again, so Delete
  // waits for the answer to this opening.
  const checking = open && isFetching;
  const stories = usage?.stories ?? [];
  const hidden = usage?.hidden_count ?? 0;
  const total = stories.length + hidden;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t('mapDelete.title')}</AlertDialogTitle>
          <AlertDialogDescription>
            <Trans i18nKey="mapDelete.description" t={t} values={{ mapName }} components={{ 1: <strong /> }} />
          </AlertDialogDescription>
        </AlertDialogHeader>
        {/* Always mounted, so screen readers announce the text when it appears. */}
        <p role="status" className={checking ? 'text-sm text-muted-foreground' : 'sr-only'}>
          {checking ? t('mapDelete.checkingStories') : ''}
        </p>
        {checking ? null : isError ? (
          <div role="alert" className="space-y-2 text-sm">
            <p>{t('mapDelete.storiesCheckFailed')}</p>
            <Button type="button" variant="outline" size="sm" onClick={() => void refetch()}>
              {t('common:actions.retry')}
            </Button>
          </div>
        ) : total > 0 && (
          <div className="space-y-2 text-sm">
            <p>{t('mapDelete.storiesUsing', { count: total })}</p>
            <ul className="list-disc space-y-1 pl-5">
              {stories.map((story) => (
                <li key={story.id}>
                  <Link to={`/stories/${story.id}`} className="text-primary hover:underline">
                    {story.title}
                  </Link>
                </li>
              ))}
              {hidden > 0 && (
                <li className="text-muted-foreground">{t('mapDelete.hiddenStories', { count: hidden })}</li>
              )}
            </ul>
          </div>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isDeleting}>{t('common:cancel')}</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            disabled={isDeleting || checking}
            variant="destructive"
          >
            {isDeleting ? t('mapDelete.deleting') : t('common:delete')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
