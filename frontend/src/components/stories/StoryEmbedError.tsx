import { useEffect } from 'react';
import { useParams, useRouteError } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ErrorState } from '@/components/layout/ErrorState';
import { pushReportEntry } from '@/lib/report';

/**
 * The route error for a story's embed page. It stays inside the frame, which
 * any site may host, so it never navigates there: the story opens in a new tab.
 */
export function StoryEmbedError() {
  const error = useRouteError();
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation('stories');

  useEffect(() => {
    pushReportEntry({
      severity: 'error',
      source: 'react',
      message: error instanceof Error ? error.message || 'Route error' : 'Route error',
      detail: error instanceof Error ? error.stack : String(error),
    });
  }, [error]);

  return (
    <main className="flex h-dvh items-center justify-center p-6">
      <ErrorState
        title={t('embed.errorTitle')}
        message={t('embed.errorMessage')}
        className="max-w-md"
        action={
          id && (
            <a
              href={`/stories/${encodeURIComponent(id)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm font-medium text-primary underline"
            >
              {t('embed.openStory')}
            </a>
          )
        }
      />
    </main>
  );
}
