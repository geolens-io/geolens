import { Outlet } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/stores/auth-store';

export function EditorRoute() {
  const { t } = useTranslation();
  const isEditor = useAuthStore((s) => s.isEditor());

  if (!isEditor) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <h1 className="text-4xl font-bold">{t('errors.forbidden')}</h1>
        <p className="mt-2 text-muted-foreground">
          {t('errors.forbiddenEditor')}
        </p>
      </div>
    );
  }

  return <Outlet />;
}
