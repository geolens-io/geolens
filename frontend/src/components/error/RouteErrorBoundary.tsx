import { useRouteError, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ErrorState } from '@/components/layout/ErrorState';
import { Button } from '@/components/ui/button';

export function RouteErrorBoundary() {
  const error = useRouteError();
  const navigate = useNavigate();
  const { t } = useTranslation('common');

  const message =
    error instanceof Error
      ? error.message
      : t('errorBoundary.routeMessage');

  return (
    <div className="flex items-center justify-center p-8">
      <ErrorState
        title={t('errorBoundary.routeTitle')}
        message={message}
        className="max-w-md"
        action={
          <div className="flex gap-2 justify-center">
            <Button variant="outline" size="sm" onClick={() => navigate(-1)}>
              {t('errorBoundary.routeGoBack')}
            </Button>
            <Button variant="default" size="sm" onClick={() => navigate('/')}>
              {t('errorBoundary.routeGoHome')}
            </Button>
          </div>
        }
      />
    </div>
  );
}
