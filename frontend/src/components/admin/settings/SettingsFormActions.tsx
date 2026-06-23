import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface SettingsFormActionsProps {
  dirty: Record<string, unknown>;
  hasDirty: boolean;
  envOnly: boolean;
  isSaving: boolean;
  onSave: (changes: Record<string, unknown>) => void;
  onDiscard: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}

export function SettingsFormActions({ dirty, hasDirty, envOnly, isSaving, onSave, onDiscard, onDirtyChange }: SettingsFormActionsProps) {
  const { t } = useTranslation('admin');

  useEffect(() => {
    onDirtyChange?.(hasDirty);
  }, [hasDirty, onDirtyChange]);

  return (
    <div className="flex items-center gap-3 pt-2">
      <Button onClick={() => onSave(dirty)} disabled={!hasDirty || envOnly || isSaving}>
        {isSaving && <Loader2 className="h-4 w-4 animate-spin" />}
        {isSaving ? t('settings.actions.saving', { defaultValue: 'Saving…' }) : t('common:save')}
      </Button>
      <Button variant="outline" onClick={onDiscard} disabled={!hasDirty || isSaving}>
        {t('settings.actions.discard')}
      </Button>
    </div>
  );
}
