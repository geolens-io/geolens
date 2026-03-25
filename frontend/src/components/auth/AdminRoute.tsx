import { Outlet } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/stores/auth-store';

export function AdminRoute() {
  const { t } = useTranslation();
  const isAdmin = useAuthStore((s) => s.isAdmin());

  if (!isAdmin) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <h1 className="text-4xl font-bold">{t('errors.forbidden')}</h1>
        <p className="mt-2 text-muted-foreground">
          {t('errors.forbiddenAdmin')}
        </p>
      </div>
    );
  }

  return <Outlet />;
}
