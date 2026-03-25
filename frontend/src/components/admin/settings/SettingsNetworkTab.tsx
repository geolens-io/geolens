import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SettingSourceBadge } from './SettingSourceBadge';
import { SettingsFormActions } from './SettingsFormActions';
import { findSetting } from './utils';
import { useSettingsForm } from './useSettingsForm';
import type { SettingItem } from '@/api/settings';

interface TabProps {
  settings: SettingItem[];
  envOnly: boolean;
  onSave: (changes: Record<string, unknown>) => void;
  onReset: (key: string) => void;
  isSaving: boolean;
}

const FIELDS = [
  { key: 'cors_allowed_origins', defaultValue: '' },
  { key: 'global_rate_limit', defaultValue: 60 },
] as const;

export function SettingsNetworkTab({ settings, envOnly, onSave, onReset, isSaving }: TabProps) {
  const { t } = useTranslation('admin');
  const { values, setters, dirty, hasDirty, discard } = useSettingsForm(settings, FIELDS);

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="cors-origins">{findSetting(settings, 'cors_allowed_origins')?.label ?? t('settings.network.corsAllowedOrigins')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'cors_allowed_origins')?.source ?? 'default'} settingKey="cors_allowed_origins" onReset={onReset} />
        </div>
        <p className="text-sm text-muted-foreground">{t('settings.network.corsAllowedOriginsDescription')}</p>
        <textarea
          id="cors-origins"
          value={values.cors_allowed_origins as string}
          onChange={(e) => setters.cors_allowed_origins(e.target.value)}
          disabled={envOnly}
          placeholder={t('settings.network.corsAllowedOriginsPlaceholder')}
          rows={3}
          className="flex w-full max-w-md rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="global-rate-limit">{findSetting(settings, 'global_rate_limit')?.label ?? t('settings.network.globalRateLimit')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'global_rate_limit')?.source ?? 'default'} settingKey="global_rate_limit" onReset={onReset} />
        </div>
        <p className="text-sm text-muted-foreground">{t('settings.network.globalRateLimitDescription')}</p>
        <Input
          id="global-rate-limit"
          type="number"
          min={1}
          max={1000}
          value={values.global_rate_limit as number}
          onChange={(e) => setters.global_rate_limit(Number(e.target.value))}
          disabled={envOnly}
          className="w-32"
        />
      </div>

      <SettingsFormActions dirty={dirty} hasDirty={hasDirty} envOnly={envOnly} isSaving={isSaving} onSave={onSave} onDiscard={discard} />
    </div>
  );
}
