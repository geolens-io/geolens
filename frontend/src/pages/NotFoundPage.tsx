import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { Button } from '@/components/ui/button';

export function NotFoundPage() {
  const { t } = useTranslation('common');

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
      <p className="text-6xl font-bold text-muted-foreground/50" aria-hidden="true">404</p>
      <h1 className="text-2xl font-semibold">{t('notFound.title')}</h1>
      <p className="text-sm text-muted-foreground">{t('notFound.description')}</p>
      <Button asChild>
        <Link to="/">{t('notFound.goHome')}</Link>
      </Button>
    </div>
  );
}
