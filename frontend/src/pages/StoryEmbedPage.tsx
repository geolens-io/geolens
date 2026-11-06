import { useParams } from 'react-router';
import { BookOpen, BookX } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/api/client';
import { useStory } from '@/hooks/use-stories';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useForcedTheme } from '@/components/theme-provider';
import { LoadingState } from '@/components/layout/LoadingState';
import { ErrorState } from '@/components/layout/ErrorState';
import { EmptyState } from '@/components/layout/EmptyState';
import { UnavailableState } from '@/components/layout/UnavailableState';
import { StoryReader } from '@/components/stories/StoryReader';

/**
 * /stories/:id/embed: the published story alone, for a frame on another site.
 * The API client reads this page as an anonymous reader (see isEmbedViewer), so
 * only a published public story renders, and nothing links back into the app.
 */
export function StoryEmbedPage() {
  return (
    <main className="flex h-dvh flex-col">
      <StoryEmbedContent />
    </main>
  );
}

function StoryEmbedContent() {
  const { t } = useTranslation('stories');
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, error, refetch } = useStory(id);
  const isNotFound = error instanceof ApiError && error.status === 404;
  useForcedTheme(data?.document?.settings?.theme);
  useDocumentTitle(isNotFound ? t('unavailable.title') : (data?.title ?? t('pageTitle')));

  if (isLoading) return <LoadingState className="flex-1" message={t('reader.loading')} />;
  if (isNotFound) {
    return (
      <UnavailableState
        icon={BookX}
        title={t('unavailable.title')}
        body={<p className="mx-auto max-w-md text-sm text-muted-foreground">{t('embed.unavailable')}</p>}
        actions={null}
      />
    );
  }
  if (error || !data) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <ErrorState message={t('reader.loadFailed')} onRetry={() => refetch()} />
      </div>
    );
  }
  const chapters = data.document?.chapters ?? [];
  if (chapters.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <EmptyState icon={BookOpen} className="w-full max-w-xl" title={data.title} description={t('reader.noChapters')} />
      </div>
    );
  }
  return (
    <StoryReader
      key={data.id}
      chromeless
      storyId={data.id}
      coverAssetId={data.cover_asset_id}
      title={data.title}
      summary={data.summary}
      chapters={chapters}
      readerTheme={data.reader_theme}
      settings={data.document?.settings}
    />
  );
}
