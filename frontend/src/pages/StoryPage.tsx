import { Link, useParams } from 'react-router';
import { BookOpen, Pencil } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/api/client';
import { useStory } from '@/hooks/use-stories';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { usePermissions } from '@/hooks/use-permissions';
import { Button } from '@/components/ui/button';
import { LoadingState } from '@/components/layout/LoadingState';
import { ErrorState } from '@/components/layout/ErrorState';
import { EmptyState } from '@/components/layout/EmptyState';
import { StoryReader } from '@/components/stories/StoryReader';
import { StoryUnavailableState } from '@/components/stories/StoryUnavailableState';
import { canEditStory } from '@/components/stories/can-edit-story';

/** /stories/:id: the published story. Anyone who can read it may open it, signed in or not. */
export function StoryPage() {
  const { t } = useTranslation('stories');
  const { id } = useParams<{ id: string }>();
  const { can } = usePermissions();
  const { data, isLoading, error, refetch } = useStory(id);
  const isNotFound = error instanceof ApiError && error.status === 404;
  useDocumentTitle(isNotFound ? t('unavailable.title') : (data?.title ?? t('pageTitle')));

  if (isLoading) return <LoadingState className="flex-1" message={t('reader.loading')} />;
  if (isNotFound) return <StoryUnavailableState returnTo={`/stories/${id}`} />;
  if (error || !data) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <ErrorState message={t('reader.loadFailed')} onRetry={() => refetch()} />
      </div>
    );
  }

  const editHref = canEditStory(can, data) ? `/stories/${data.id}/edit` : undefined;
  const chapters = data.document?.chapters ?? [];
  if (chapters.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <EmptyState
          icon={BookOpen}
          className="w-full max-w-xl"
          title={data.title}
          description={data.document ? t('reader.noChapters') : t('reader.notPublished')}
          action={
            editHref && (
              <Button asChild>
                <Link to={editHref}>
                  <Pencil className="h-4 w-4" aria-hidden="true" />
                  {t('reader.edit')}
                </Link>
              </Button>
            )
          }
        />
      </div>
    );
  }

  return (
    <StoryReader
      key={data.id}
      title={data.title}
      summary={data.summary}
      chapters={chapters}
      editHref={editHref}
    />
  );
}
