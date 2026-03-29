import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';
import { useConfigMode } from '@/hooks/use-settings';

export function EnvOnlyBanner() {
  const { t } = useTranslation('admin');
  const { data } = useConfigMode();

  if (!data?.env_only) return null;

  return (
    <div className="flex items-start gap-3 rounded-lg border border-info/30 bg-info/5 p-4">
      <Info className="mt-0.5 h-5 w-5 shrink-0 text-info" />
      <div className="text-sm text-foreground">
        <p className="font-medium">{t('settings.envOnly.title')}</p>
        <p className="mt-1 text-muted-foreground">
          {t('settings.envOnly.descriptionPrefix')}{' '}
          <code className="rounded bg-info/10 px-1 py-0.5 text-xs font-mono">ENV_ONLY_CONFIG=false</code>{' '}
          {t('settings.envOnly.descriptionSuffix')}
        </p>
      </div>
    </div>
  );
}
