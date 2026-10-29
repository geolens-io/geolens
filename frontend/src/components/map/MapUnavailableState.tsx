import { Link } from 'react-router';
import { MapPinOff } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/api/client';
import { useAuthStore } from '@/stores/auth-store';
import { Button } from '@/components/ui/button';
import { UnavailableState } from '@/components/layout/UnavailableState';

interface MapUnavailableStateProps {
  error: unknown;
  mapId: string | undefined;
}

/** Shown in place of a map that failed to load; the title follows the error's status. */
export function MapUnavailableState({ error, mapId }: MapUnavailableStateProps) {
  const { t } = useTranslation('common');
  const hasToken = useAuthStore((s) => !!s.token);
  const is403 = error instanceof ApiError && error.status === 403;
  const is404 = error instanceof ApiError && error.status === 404;
  // A signed-out visitor to a private map needs to sign in, so offer that first.
  const isAnonymous = !hasToken;

  return (
    <UnavailableState
      icon={MapPinOff}
      title={
        is403
          ? t('viewer.accessDenied', { defaultValue: 'Access denied' })
          : is404
            ? t('viewer.mapNotFound')
            : t('viewer.loadFailed')
      }
      body={
        <>
          <p className="mx-auto max-w-md text-sm text-muted-foreground">
            {t('viewer.mapNotFoundDescription')}
          </p>
          <p className="mx-auto max-w-md text-sm text-muted-foreground">
            {isAnonymous
              ? t('viewer.anonMapRecovery')
              : t('viewer.authMapRecovery', {
                  defaultValue: 'Open your maps list to confirm access, or head back to the catalog to keep working.',
                })}
          </p>
        </>
      }
      actions={
        <>
          {isAnonymous ? (
            <Button asChild>
              <Link to="/login" state={{ from: `/maps/${mapId ?? ''}` }}>
                {t('viewer.signIn')}
              </Link>
            </Button>
          ) : (
            <Button asChild>
              <Link to="/maps">
                {t('viewer.openMaps', { defaultValue: 'Open maps' })}
              </Link>
            </Button>
          )}
          <Button variant="outline" asChild>
            <Link to="/">
              {t('viewer.browseCatalog', { defaultValue: 'Browse catalog' })}
            </Link>
          </Button>
        </>
      }
    />
  );
}
