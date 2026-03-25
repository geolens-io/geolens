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
  onDirtyChange?: (dirty: boolean) => void;
}

const FIELDS = [
  { key: 'upload_max_size_mb', defaultValue: 500 },
  { key: 'upload_allowed_extensions', defaultValue: '' },
  { key: 'tile_cache_ttl', defaultValue: 300 },
] as const;

export function SettingsStorageTab({ settings, envOnly, onSave, onReset, isSaving, onDirtyChange }: TabProps) {
  const { t } = useTranslation('admin');
  const { values, setters, dirty, hasDirty, discard } = useSettingsForm(settings, FIELDS);

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="upload-max-size">{t('settings.uploads.maxSizeMb')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'upload_max_size_mb')?.source ?? 'default'} settingKey="upload_max_size_mb" onReset={onReset} />
        </div>
        <p className="text-sm text-muted-foreground">{t('settings.uploads.maxSizeMbDescription')}</p>
        <Input
          id="upload-max-size"
          type="number"
          min={1}
          max={10000}
          value={values.upload_max_size_mb as number}
          onChange={(e) => setters.upload_max_size_mb(Number(e.target.value))}
          disabled={envOnly}
          className="w-32"
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="allowed-extensions">{t('settings.uploads.allowedExtensions')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'upload_allowed_extensions')?.source ?? 'default'} settingKey="upload_allowed_extensions" onReset={onReset} />
        </div>
        <p className="text-sm text-muted-foreground">{t('settings.uploads.allowedExtensionsDescription')}</p>
        <Input
          id="allowed-extensions"
          type="text"
          value={values.upload_allowed_extensions as string}
          onChange={(e) => setters.upload_allowed_extensions(e.target.value)}
          disabled={envOnly}
          className="w-80"
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="tile-cache-ttl">{t('settings.uploads.tileCacheTtl')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'tile_cache_ttl')?.source ?? 'default'} settingKey="tile_cache_ttl" onReset={onReset} />
        </div>
        <p className="text-sm text-muted-foreground">{t('settings.uploads.tileCacheTtlDescription')}</p>
        <Input
          id="tile-cache-ttl"
          type="number"
          min={0}
          max={86400}
          value={values.tile_cache_ttl as number}
          onChange={(e) => setters.tile_cache_ttl(Number(e.target.value))}
          disabled={envOnly}
          className="w-32"
        />
      </div>

      <SettingsFormActions dirty={dirty} hasDirty={hasDirty} envOnly={envOnly} isSaving={isSaving} onSave={onSave} onDiscard={discard} onDirtyChange={onDirtyChange} />
    </div>
  );
}
