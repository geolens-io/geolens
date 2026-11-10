import { useState } from 'react';
import { Link } from 'react-router';
import { BookOpen, Calendar, Copy, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Trans, useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { EmptyState } from '@/components/layout/EmptyState';
import { ErrorState } from '@/components/layout/ErrorState';
import { Pagination } from '@/components/layout/Pagination';
import { MapCardSkeleton } from '@/components/maps/MapCardSkeleton';
import { VisibilityBadge } from '@/components/maps/VisibilityBadge';
import { storyAssetPath } from '@/api/stories';
import { AssetImage } from '@/components/widgets/image/AssetImage';
import { useDeleteStory, useDuplicateStory, useStories } from '@/hooks/use-stories';
import { usePermissions } from '@/hooks/use-permissions';
import { canEditStory } from './can-edit-story';
import { formatDate } from '@/lib/format';
import type { StorySummary } from '@/types/api';

const PAGE_SIZE = 20;

/**
 * The stories the caller may read, with the actions the API grants them:
 * anyone can open one, a user who can create stories can duplicate it, and
 * its owner or an admin (`can_edit`) can delete it.
 */
export function StoriesList() {
  const { t } = useTranslation('stories');
  const { can } = usePermissions();
  const canCreate = can('edit_metadata');
  const [skip, setSkip] = useState(0);
  const [deleting, setDeleting] = useState<StorySummary | null>(null);
  const { data, isLoading, isFetching, error, refetch } = useStories({ skip, limit: PAGE_SIZE });
  const duplicateStory = useDuplicateStory();
  const deleteStory = useDeleteStory();

  function handleDuplicate(story: StorySummary) {
    duplicateStory.mutate(story.id, {
      onSuccess: (copy) => toast.success(t('list.duplicated', { title: copy.title })),
    });
  }

  function handleDeleteConfirm() {
    if (!deleting) return;
    // The last story on a later page is going, so that page will be empty.
    const leavingPage = data?.stories.length === 1 && skip > 0;
    deleteStory.mutate(
      { id: deleting.id, leavingPage },
      {
        onSuccess: () => {
          toast.success(t('list.deleted'));
          setDeleting(null);
          if (leavingPage) setSkip(skip - PAGE_SIZE);
        },
      },
    );
  }

  return (
    <div className="space-y-4">
      {isLoading && Array.from({ length: 3 }).map((_, i) => <MapCardSkeleton key={i} />)}

      {error && (
        <ErrorState message={t('list.loadFailed', { message: error.message })} onRetry={() => refetch()} />
      )}

      {data && data.total === 0 && (
        <EmptyState
          icon={BookOpen}
          title={t('list.empty')}
          description={t('list.emptyDescription')}
          announce={!isFetching}
        />
      )}

      {data?.stories.map((story) => (
        <StoryCard
          key={story.id}
          story={story}
          canEdit={canEditStory(can, story)}
          onDuplicate={canCreate ? handleDuplicate : undefined}
          duplicating={duplicateStory.isPending && duplicateStory.variables === story.id}
          onDelete={story.can_edit ? setDeleting : undefined}
        />
      ))}

      {data && data.total > 0 && (
        <Pagination total={data.total} offset={skip} limit={PAGE_SIZE} onPageChange={setSkip} />
      )}

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t('list.deleteTitle')}
        description={
          <Trans
            t={t}
            i18nKey="list.deleteDescription"
            values={{ title: deleting?.title ?? '' }}
            components={{ 1: <strong /> }}
          />
        }
        confirm={{
          label: t('list.delete'),
          onClick: handleDeleteConfirm,
          variant: 'destructive',
          pending: deleteStory.isPending,
        }}
      />
    </div>
  );
}

/** The cover, decorative beside the title, or the story icon without one. */
function StoryCardCover({ story }: { story: StorySummary }) {
  return (
    <AssetImage
      path={story.cover_asset_id ? storyAssetPath(story.id, story.cover_asset_id, 'card') : null}
      alt=""
      lazy
      className="h-12 w-16 shrink-0 rounded object-cover"
      placeholderClassName="h-12 w-16 shrink-0"
      fallback={<BookOpen className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" />}
    />
  );
}

interface StoryCardProps {
  story: StorySummary;
  canEdit: boolean;
  onDuplicate?: (story: StorySummary) => void;
  duplicating: boolean;
  onDelete?: (story: StorySummary) => void;
}

function StoryCard({ story, canEdit, onDuplicate, duplicating, onDelete }: StoryCardProps) {
  const { t } = useTranslation('stories');
  return (
    <Card
      data-testid="story-card"
      density="flush"
      className="flex-row items-start gap-4 p-4 transition-[color,background-color,box-shadow,border-color] duration-200 ease-out hover:border-primary/20 hover:bg-accent/50 hover:shadow-md"
    >
      <StoryCardCover story={story} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Link
            to={`/stories/${story.id}`}
            className="truncate text-base font-semibold text-foreground transition-colors hover:text-primary"
          >
            {story.title}
          </Link>
          <VisibilityBadge visibility={story.visibility} />
          {!story.published_at && (
            <Badge variant="secondary" className="shrink-0">
              {t('list.unpublished')}
            </Badge>
          )}
        </div>
        {story.summary && (
          <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{story.summary}</p>
        )}
        <span className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground">
          <Calendar className="h-3 w-3" aria-hidden="true" />
          {t('list.updated', { date: formatDate(story.updated_at) })}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {canEdit && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button asChild variant="ghost" size="icon" className="text-muted-foreground">
                <Link to={`/stories/${story.id}/edit`} aria-label={t('list.editNamed', { title: story.title })}>
                  <Pencil className="h-4 w-4" />
                </Link>
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top">{t('list.edit')}</TooltipContent>
          </Tooltip>
        )}
        {onDuplicate && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground"
                onClick={() => onDuplicate(story)}
                disabled={duplicating}
                aria-label={t('list.duplicateNamed', { title: story.title })}
              >
                <Copy className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top">{t('list.duplicate')}</TooltipContent>
          </Tooltip>
        )}
        {onDelete && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground transition-colors duration-150 hover:text-destructive"
                onClick={() => onDelete(story)}
                aria-label={t('list.deleteNamed', { title: story.title })}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top">{t('list.delete')}</TooltipContent>
          </Tooltip>
        )}
      </div>
    </Card>
  );
}
