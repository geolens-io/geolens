import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useNewServerVersion } from '@/hooks/use-new-version';

export function NewVersionBanner() {
  const { t } = useTranslation('common');
  const serverVersion = useNewServerVersion();
  // Holds the server version that was dismissed, so a later release re-prompts.
  const [dismissed, setDismissed] = useState<string | null>(null);

  if (!serverVersion || dismissed === serverVersion) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="relative flex items-center justify-center gap-3 border-b border-info/30 bg-info/10 px-8 py-1.5 text-sm text-info"
    >
      <span>{t('newVersion.message')}</span>
      <Button type="button" size="sm" variant="outline" onClick={() => window.location.reload()}>
        {t('newVersion.reload')}
      </Button>
      <button
        type="button"
        onClick={() => setDismissed(serverVersion)}
        aria-label={t('close')}
        className="absolute end-2 top-1/2 -translate-y-1/2 rounded p-0.5 opacity-70 hover:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-current"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
