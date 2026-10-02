import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
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
  settingsUpdatedAt?: number;
  onDirtyChange?: (dirty: boolean) => void;
}

const FIELDS = [
  { key: 'upload_max_size_mb', defaultValue: 500 },
  {
    key: 'upload_allowed_extensions',
    // Client-side fallback for a response that omits the setting. Kept in
    // step with Settings.upload_allowed_extensions so it never shows a
    // narrower list than the server enforces.
    defaultValue: '.zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls,.parquet,.fgb,.kml,.kmz,.3tz,.laz',
  },
  { key: 'tile_cache_ttl', defaultValue: 300 },
  { key: 'max_storage_bytes_per_user', defaultValue: 0 },
  { key: 'max_datasets_per_user', defaultValue: 0 },
] as const;

const GIB = 1024 ** 3;
type StorageUnit = 'bytes' | 'gib';

function displayStorage(bytes: number, unit: StorageUnit): string {
  if (unit === 'bytes') return String(bytes);
  const whole = BigInt(bytes) / BigInt(GIB);
  const remainder = BigInt(bytes) % BigInt(GIB);
  if (remainder === 0n) return String(whole);
  const fraction = (remainder * 10n ** 30n / BigInt(GIB)).toString().padStart(30, '0').replace(/0+$/, '');
  return `${whole}.${fraction}`;
}

function storageBytes(quantity: string, unit: StorageUnit): number | null {
  if (!/^\d+(?:\.\d+)?$/.test(quantity)) return null;
  const [whole, fraction = ''] = quantity.split('.');
  if (unit === 'bytes' && fraction) return null;
  const scale = 10n ** BigInt(fraction.length);
  const numerator = (BigInt(whole) * scale + BigInt(fraction || '0')) * BigInt(unit === 'gib' ? GIB : 1);
  if (numerator % scale !== 0n) return null;
  const bytes = numerator / scale;
  return bytes <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(bytes) : null;
}

export function SettingsStorageTab({ settings, envOnly, onSave, onReset, isSaving, settingsUpdatedAt, onDirtyChange }: TabProps) {
  const { t } = useTranslation('admin');
  const { values, setters, dirty, hasDirty, discard } = useSettingsForm(settings, FIELDS, isSaving, settingsUpdatedAt);
  const storedBytes = values.max_storage_bytes_per_user as number;
  const [storageUnit, setStorageUnit] = useState<StorageUnit>(() => storedBytes && storedBytes % GIB !== 0 ? 'bytes' : 'gib');
  const [storageQuantity, setStorageQuantity] = useState(() => displayStorage(storedBytes, storageUnit));
  const editedBytes = useRef(storedBytes);
  const quantityBytes = storageBytes(storageQuantity, storageUnit);

  useEffect(() => {
    if (storedBytes !== editedBytes.current) {
      editedBytes.current = storedBytes;
      const unit = storedBytes && storedBytes % GIB !== 0 ? 'bytes' : 'gib';
      setStorageUnit(unit);
      setStorageQuantity(displayStorage(storedBytes, unit));
    }
  }, [storedBytes]);

  function updateStorageQuantity(quantity: string) {
    setStorageQuantity(quantity);
    const bytes = storageBytes(quantity, storageUnit);
    if (bytes !== null) {
      editedBytes.current = bytes;
      setters.max_storage_bytes_per_user(bytes);
    }
  }

  function updateStorageUnit(unit: StorageUnit) {
    setStorageUnit(unit);
    setStorageQuantity(displayStorage(storedBytes, unit));
  }

  function discardChanges() {
    discard();
    const bytes = findSetting(settings, 'max_storage_bytes_per_user')?.value as number ?? 0;
    editedBytes.current = bytes;
    const unit = bytes && bytes % GIB !== 0 ? 'bytes' : 'gib';
    setStorageUnit(unit);
    setStorageQuantity(displayStorage(bytes, unit));
  }

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

      {/* Per-user quotas — global caps applied to every user (enforced at ingest).
          Grouped so they read as limits, not more global upload config. */}
      <div className="space-y-4 border rounded-md p-4" role="group" aria-labelledby="per-user-limits-heading">
        <div>
          <h3 id="per-user-limits-heading" className="text-sm font-medium">{t('settings.uploads.perUserLimitsTitle')}</h3>
          <p className="text-sm text-muted-foreground mt-1">{t('settings.uploads.perUserLimitsDescription')}</p>
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Label htmlFor="max-storage-per-user">{t('settings.uploads.maxStoragePerUser')}</Label>
            <SettingSourceBadge source={findSetting(settings, 'max_storage_bytes_per_user')?.source ?? 'default'} settingKey="max_storage_bytes_per_user" onReset={onReset} />
          </div>
          <p id="max-storage-help" className="text-sm text-muted-foreground">{t('settings.uploads.maxStoragePerUserDescription')}</p>
          <div className="flex flex-wrap gap-2">
            <Input
              id="max-storage-per-user"
              type="number"
              min={0}
              step="any"
              value={storageQuantity}
              onChange={(e) => updateStorageQuantity(e.target.value)}
              aria-invalid={quantityBytes === null}
              aria-describedby={quantityBytes === null ? 'max-storage-error' : 'max-storage-help'}
              disabled={envOnly}
              className="w-40"
            />
            <Select value={storageUnit} onValueChange={(unit: StorageUnit) => updateStorageUnit(unit)} disabled={envOnly}>
              <SelectTrigger aria-label={t('settings.uploads.storageUnit')} className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="gib">{t('settings.uploads.gib')}</SelectItem>
                <SelectItem value="bytes">{t('settings.uploads.bytes')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {quantityBytes === null && <p id="max-storage-error" className="text-sm text-destructive">{t('settings.uploads.invalidStorageQuantity')}</p>}
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Label htmlFor="max-datasets-per-user">{t('settings.uploads.maxDatasetsPerUser')}</Label>
            <SettingSourceBadge source={findSetting(settings, 'max_datasets_per_user')?.source ?? 'default'} settingKey="max_datasets_per_user" onReset={onReset} />
          </div>
          <p className="text-sm text-muted-foreground">{t('settings.uploads.maxDatasetsPerUserDescription')}</p>
          <Input
            id="max-datasets-per-user"
            type="number"
            min={0}
            step={1}
            value={values.max_datasets_per_user as number}
            onChange={(e) => setters.max_datasets_per_user(Number(e.target.value))}
            disabled={envOnly}
            className="w-32"
          />
        </div>
      </div>

      <SettingsFormActions dirty={dirty} hasDirty={hasDirty} envOnly={envOnly || quantityBytes === null} isSaving={isSaving} onSave={onSave} onDiscard={discardChanges} onDirtyChange={onDirtyChange} />
    </div>
  );
}
