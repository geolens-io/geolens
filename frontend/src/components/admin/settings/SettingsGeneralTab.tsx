import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { SettingSourceBadge } from './SettingSourceBadge';
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
  { key: 'require_metadata_for_publish', defaultValue: false },
  { key: 'public_app_url', defaultValue: '' },
  { key: 'public_api_url', defaultValue: '' },
  { key: 'log_level', defaultValue: 'INFO' },
  { key: 'log_json', defaultValue: false },
] as const;

export function SettingsGeneralTab({ settings, envOnly, onSave, onReset, isSaving }: TabProps) {
  const { t } = useTranslation('admin');
  const { values, setters, dirty, hasDirty, discard } = useSettingsForm(settings, FIELDS);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between max-w-md">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <Label htmlFor="require-metadata-toggle">{t('settings.general.requireMetadata')}</Label>
            <SettingSourceBadge source={findSetting(settings, 'require_metadata_for_publish')?.source ?? 'default'} settingKey="require_metadata_for_publish" onReset={onReset} />
          </div>
          <p className="text-sm text-muted-foreground">{t('settings.general.requireMetadataDescription')}</p>
        </div>
        <Switch
          id="require-metadata-toggle"
          checked={values.require_metadata_for_publish as boolean}
          onCheckedChange={setters.require_metadata_for_publish}
          disabled={envOnly}
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="public-app-url">{t('settings.general.publicAppUrl')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'public_app_url')?.source ?? 'default'} settingKey="public_app_url" onReset={onReset} />
        </div>
        <p className="text-sm text-muted-foreground">{t('settings.general.publicAppUrlDescription')}</p>
        <Input
          id="public-app-url"
          type="text"
          value={values.public_app_url as string}
          onChange={(e) => setters.public_app_url(e.target.value)}
          disabled={envOnly}
          className="max-w-md"
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="public-api-url">{t('settings.general.publicApiUrl')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'public_api_url')?.source ?? 'default'} settingKey="public_api_url" onReset={onReset} />
        </div>
        <p className="text-sm text-muted-foreground">{t('settings.general.publicApiUrlDescription')}</p>
        <Input
          id="public-api-url"
          type="text"
          value={values.public_api_url as string}
          onChange={(e) => setters.public_api_url(e.target.value)}
          disabled={envOnly}
          className="max-w-md"
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="log-level">{t('settings.general.logLevel')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'log_level')?.source ?? 'default'} settingKey="log_level" onReset={onReset} />
        </div>
        <Select value={values.log_level as string} onValueChange={setters.log_level} disabled={envOnly}>
          <SelectTrigger id="log-level" className="w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="DEBUG">DEBUG</SelectItem>
            <SelectItem value="INFO">INFO</SelectItem>
            <SelectItem value="WARNING">WARNING</SelectItem>
            <SelectItem value="ERROR">ERROR</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center justify-between max-w-md">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <Label htmlFor="log-json-toggle">{t('settings.general.logJsonLabel')}</Label>
            <SettingSourceBadge source={findSetting(settings, 'log_json')?.source ?? 'default'} settingKey="log_json" onReset={onReset} />
          </div>
          <p className="text-sm text-muted-foreground">{t('settings.general.logJsonDescription')}</p>
        </div>
        <Switch
          id="log-json-toggle"
          checked={values.log_json as boolean}
          onCheckedChange={setters.log_json}
          disabled={envOnly}
        />
      </div>

      <div className="flex items-center gap-3 pt-2">
        <Button onClick={() => onSave(dirty)} disabled={!hasDirty || envOnly || isSaving}>
          {isSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          {t('common:save')}
        </Button>
        <Button variant="outline" onClick={discard} disabled={!hasDirty || isSaving}>
          {t('settings.actions.discard')}
        </Button>
      </div>
    </div>
  );
}
