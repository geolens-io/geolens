import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';
import { useConfigMode } from '@/hooks/use-settings';

export function EnvOnlyBanner() {
  const { t } = useTranslation('admin');
  const { data } = useConfigMode();

  if (!data?.env_only) return null;

  return (
    <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-900 dark:bg-blue-950/50">
      <Info className="mt-0.5 h-5 w-5 shrink-0 text-blue-600 dark:text-blue-400" />
      <div className="text-sm text-blue-800 dark:text-blue-200">
        <p className="font-medium">{t('settings.envOnly.title')}</p>
        <p className="mt-1 text-blue-700 dark:text-blue-300">
          {t('settings.envOnly.descriptionPrefix')}{' '}
          <code className="rounded bg-blue-100 px-1 py-0.5 text-xs font-mono dark:bg-blue-900">ENV_ONLY_CONFIG=false</code>{' '}
          {t('settings.envOnly.descriptionSuffix')}
        </p>
      </div>
    </div>
  );
}
