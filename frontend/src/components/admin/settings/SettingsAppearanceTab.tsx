import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { useBranding, useUpdateBranding } from '@/hooks/use-settings';
import type { SettingItem } from '@/api/settings';

interface TabProps {
  settings: SettingItem[];
  envOnly: boolean;
  onSave: (changes: Record<string, unknown>) => void;
  onReset: (key: string) => void;
  isSaving: boolean;
  onDirtyChange?: (dirty: boolean) => void;
}

export function SettingsAppearanceTab({ onDirtyChange }: TabProps) {
  const { t } = useTranslation('admin');
  const { data: branding } = useBranding();
  const updateBranding = useUpdateBranding();
  const showBadge = branding?.show_badge ?? true;

  function handleToggle(checked: boolean) {
    updateBranding.mutate({ show_badge: checked });
  }

  // This tab saves immediately on toggle, so never dirty
  useEffect(() => { onDirtyChange?.(false); }, [onDirtyChange]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('settings.appearance.branding.title')}</CardTitle>
        <CardDescription>{t('settings.appearance.branding.description')}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between">
          <Label htmlFor="show-badge">{t('settings.appearance.branding.showBadge')}</Label>
          <Switch
            id="show-badge"
            checked={showBadge}
            onCheckedChange={handleToggle}
            disabled={updateBranding.isPending}
          />
        </div>
      </CardContent>
    </Card>
  );
}
