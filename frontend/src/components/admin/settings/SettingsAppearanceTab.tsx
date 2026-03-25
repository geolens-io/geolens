import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Trash2 } from 'lucide-react';
import { SettingsFormActions } from './SettingsFormActions';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { SettingSourceBadge } from './SettingSourceBadge';
import { findSetting } from './utils';
import { useSettingsForm } from './useSettingsForm';
import type { SettingItem } from '@/api/settings';

interface BasemapEntry {
  id: string;
  label: string;
  url: string;
  enabled: boolean;
  is_preset: boolean;
}

interface MapDefaultsValue {
  center_lat: number;
  center_lng: number;
  zoom: number;
}

interface TabProps {
  settings: SettingItem[];
  envOnly: boolean;
  onSave: (changes: Record<string, unknown>) => void;
  onReset: (key: string) => void;
  isSaving: boolean;
}

function isValidTileUrl(url: string): boolean {
  if (url.endsWith('.json')) return true;
  return url.includes('{z}') && url.includes('{x}') && url.includes('{y}');
}

const APPEARANCE_FIELDS = [
  { key: 'basemaps', defaultValue: [] as BasemapEntry[], compare: 'json' as const },
  { key: 'map_defaults', defaultValue: { center_lat: 20, center_lng: 0, zoom: 2 } as MapDefaultsValue, compare: 'json' as const },
] as const;

export function SettingsAppearanceTab({ settings, envOnly, onSave, onReset, isSaving }: TabProps) {
  const { t } = useTranslation('admin');
  const { values, setters, dirty, hasDirty, discard } = useSettingsForm(settings, APPEARANCE_FIELDS);
  const [newName, setNewName] = useState('');
  const [newUrl, setNewUrl] = useState('');
  const [urlError, setUrlError] = useState('');

  const basemaps = values.basemaps as BasemapEntry[];
  const mapDefaults = values.map_defaults as MapDefaultsValue;

  const presets = basemaps.filter((b) => b.is_preset);
  const customs = basemaps.filter((b) => !b.is_preset);

  function handleToggle(id: string, checked: boolean) {
    setters.basemaps(basemaps.map((b) => (b.id === id ? { ...b, enabled: checked } : b)));
  }

  function handleDelete(id: string) {
    setters.basemaps(basemaps.filter((b) => b.id !== id));
  }

  function handleAdd() {
    setUrlError('');
    if (!newName.trim() || !newUrl.trim()) return;
    if (!isValidTileUrl(newUrl.trim())) {
      setUrlError(t('settings.basemaps.urlError'));
      return;
    }
    const entry: BasemapEntry = {
      id: `custom-${Date.now()}`,
      label: newName.trim(),
      url: newUrl.trim(),
      enabled: true,
      is_preset: false,
    };
    setters.basemaps([...basemaps, entry]);
    setNewName('');
    setNewUrl('');
  }

  return (
    <div className="space-y-8">
      {/* Basemaps section */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <h3 className="text-base font-medium">{t('settings.basemaps.presetsTitle')}</h3>
          <SettingSourceBadge source={findSetting(settings, 'basemaps')?.source ?? 'default'} settingKey="basemaps" onReset={onReset} />
        </div>
        <p className="text-sm text-muted-foreground">{t('settings.basemaps.presetsDescription')}</p>

        <div className="space-y-3 max-w-md">
          {presets.map((basemap) => (
            <div key={basemap.id} className="flex items-center justify-between">
              <Label>{basemap.label}</Label>
              <Switch
                checked={basemap.enabled}
                onCheckedChange={(checked) => handleToggle(basemap.id, checked)}
                disabled={envOnly}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-4">
        <h3 className="text-base font-medium">{t('settings.basemaps.customTitle')}</h3>
        <p className="text-sm text-muted-foreground">{t('settings.basemaps.customDescription')}</p>

        <div className="space-y-3">
          {customs.map((basemap) => (
            <div key={basemap.id} className="flex items-center justify-between gap-4">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{basemap.label}</p>
                <p className="text-xs text-muted-foreground truncate">{basemap.url}</p>
              </div>
              <div className="flex items-center gap-2">
                <Switch
                  checked={basemap.enabled}
                  onCheckedChange={(checked) => handleToggle(basemap.id, checked)}
                  disabled={envOnly}
                />
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => handleDelete(basemap.id)}
                  disabled={envOnly}
                  className="h-7 w-7"
                  aria-label={t('settings.basemaps.removeBasemap')}
                >
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />
                </Button>
              </div>
            </div>
          ))}

          {!envOnly && (
            <div className="border-t pt-4 space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="basemap-name">{t('settings.basemaps.nameLabel')}</Label>
                  <Input
                    id="basemap-name"
                    placeholder={t('settings.basemaps.namePlaceholder')}
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="basemap-url">{t('settings.basemaps.tileUrlLabel')}</Label>
                  <Input
                    id="basemap-url"
                    placeholder={t('settings.basemaps.tileUrlPlaceholder')}
                    value={newUrl}
                    onChange={(e) => {
                      setNewUrl(e.target.value);
                      if (urlError) setUrlError('');
                    }}
                  />
                  {urlError && <p className="text-xs text-destructive">{urlError}</p>}
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={handleAdd}>
                {t('settings.basemaps.add')}
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* Map Defaults section */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <h3 className="text-base font-medium">{t('settings.mapDefaults.cardTitle')}</h3>
          <SettingSourceBadge source={findSetting(settings, 'map_defaults')?.source ?? 'default'} settingKey="map_defaults" onReset={onReset} />
        </div>
        <p className="text-sm text-muted-foreground">{t('settings.mapDefaults.cardDescription')}</p>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-lg">
          <div className="space-y-1.5">
            <Label htmlFor="map-lat">{t('settings.mapDefaults.latitude')}</Label>
            <Input
              id="map-lat"
              type="number"
              value={mapDefaults.center_lat}
              onChange={(e) => setters.map_defaults({ ...mapDefaults, center_lat: Number(e.target.value) })}
              min={-90}
              max={90}
              step={0.001}
              disabled={envOnly}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="map-lng">{t('settings.mapDefaults.longitude')}</Label>
            <Input
              id="map-lng"
              type="number"
              value={mapDefaults.center_lng}
              onChange={(e) => setters.map_defaults({ ...mapDefaults, center_lng: Number(e.target.value) })}
              min={-180}
              max={180}
              step={0.001}
              disabled={envOnly}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="map-zoom">{t('settings.mapDefaults.zoomLevel')}</Label>
            <Input
              id="map-zoom"
              type="number"
              value={mapDefaults.zoom}
              onChange={(e) => setters.map_defaults({ ...mapDefaults, zoom: Number(e.target.value) })}
              min={0}
              max={22}
              step={0.1}
              disabled={envOnly}
            />
          </div>
        </div>
      </div>

      <SettingsFormActions dirty={dirty} hasDirty={hasDirty} envOnly={envOnly} isSaving={isSaving} onSave={onSave} onDiscard={discard} />
    </div>
  );
}
