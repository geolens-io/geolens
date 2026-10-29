import { Link } from 'react-router';
import { BookX } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { UnavailableState } from '@/components/layout/UnavailableState';
import { useAuthStore } from '@/stores/auth-store';

/**
 * Shown for a story that's missing or that the reader can't open. The API
 * answers 404 for both, so a signed-out reader is offered sign-in first.
 */
export function StoryUnavailableState({ returnTo }: { returnTo: string }) {
  const { t } = useTranslation('stories');
  const isAnonymous = !useAuthStore((s) => !!s.token);
  return (
    <UnavailableState
      icon={BookX}
      title={t('unavailable.title')}
      body={
        <p className="mx-auto max-w-md text-sm text-muted-foreground">
          {isAnonymous ? t('unavailable.anonymous') : t('unavailable.signedIn')}
        </p>
      }
      actions={
        <>
          {isAnonymous ? (
            <Button asChild>
              <Link to="/login" state={{ from: returnTo }}>
                {t('unavailable.signIn')}
              </Link>
            </Button>
          ) : (
            <Button asChild>
              <Link to="/maps?type=stories">{t('unavailable.openStories')}</Link>
            </Button>
          )}
          <Button variant="outline" asChild>
            <Link to="/">{t('unavailable.browseCatalog')}</Link>
          </Button>
        </>
      }
    />
  );
}
