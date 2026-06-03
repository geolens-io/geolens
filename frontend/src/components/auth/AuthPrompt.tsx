import { Link, useLocation } from 'react-router';
import { useTranslation } from 'react-i18next';
import { LogIn } from 'lucide-react';

export function AuthPrompt({ action }: { action: string }) {
  const location = useLocation();
  const { t } = useTranslation('auth');
  return (
    <Link
      to="/login"
      state={{ from: location.pathname }}
      className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
    >
      <LogIn className="h-3.5 w-3.5" />
      {t('signInTo', { action })}
    </Link>
  );
}
