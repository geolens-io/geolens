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
import { getWidgets } from '@/components/map-widgets';
import type { SettingItem, BasemapEntry } from '@/api/settings';

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
  onDirtyChange?: (dirty: boolean) => void;
}

function isValidTileUrl(url: string): boolean {
  const basePath = url.split('?')[0].replace(/\/+$/, '');
  if (basePath.endsWith('.json')) return true;
  if (url.includes('/styles/')) return true;
  return url.includes('{z}') && url.includes('{x}') && url.includes('{y}');
}

interface WidgetTogglesProps {
  settings: SettingItem[];
  enabledWidgets: string[];
  onChangeEnabled: (ids: string[]) => void;
  onReset: (key: string) => void;
  envOnly: boolean;
}

function WidgetToggles({ settings, enabledWidgets, onChangeEnabled, onReset, envOnly }: WidgetTogglesProps) {
  const { t } = useTranslation('admin');
  const { t: tBuilder } = useTranslation('builder');
  const registeredWidgets = getWidgets();
  if (registeredWidgets.length === 0) return null;

  // enabledWidgets is already coerced: [] from server → full ID list
  function handleToggle(id: string, checked: boolean) {
    onChangeEnabled(
      checked
        ? [...enabledWidgets.filter((wid) => wid !== id), id]
        : enabledWidgets.filter((wid) => wid !== id),
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <h3 className="text-base font-medium">{t('settings.widgets.title')}</h3>
        <SettingSourceBadge source={findSetting(settings, 'enabled_widgets')?.source ?? 'default'} settingKey="enabled_widgets" onReset={onReset} />
      </div>
      <p className="text-sm text-muted-foreground">{t('settings.widgets.description')}</p>

      <div className="space-y-3 max-w-md">
        {registeredWidgets.map((w) => {
          const Icon = w.icon;
          return (
            <div key={w.id} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4 text-muted-foreground" />
                <Label>{tBuilder(w.labelKey)}</Label>
              </div>
              <Switch
                checked={enabledWidgets.includes(w.id)}
                onCheckedChange={(checked) => handleToggle(w.id, checked)}
                disabled={envOnly}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Coerce server null (never configured) to full list; [] means explicitly none
function coerceEnabledWidgets(v: unknown): string[] {
  if (v == null) return getWidgets().map((w) => w.id);
  return Array.isArray(v) ? v as string[] : [];
}

const MAP_FIELDS = [
  { key: 'basemaps', defaultValue: [] as BasemapEntry[], compare: 'json' as const },
  { key: 'map_defaults', defaultValue: { center_lat: 20, center_lng: 0, zoom: 2 } as MapDefaultsValue, compare: 'json' as const },
  { key: 'enabled_widgets', defaultValue: [] as string[], compare: 'json' as const, coerce: coerceEnabledWidgets },
] as const;

export function SettingsMapTab({ settings, envOnly, onSave, onReset, isSaving, onDirtyChange }: TabProps) {
  const { t } = useTranslation('admin');
  const { values, setters, dirty, hasDirty, discard } = useSettingsForm(settings, MAP_FIELDS);
  const [newName, setNewName] = useState('');
  const [newUrl, setNewUrl] = useState('');
  const [newAttribution, setNewAttribution] = useState('');
  const [newApiKey, setNewApiKey] = useState('');
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
      ...(newAttribution.trim() ? { attribution: newAttribution.trim() } : {}),
      ...(newApiKey.trim() ? { api_key: newApiKey.trim() } : {}),
    };
    setters.basemaps([...basemaps, entry]);
    setNewName('');
    setNewUrl('');
    setNewAttribution('');
    setNewApiKey('');
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
            <div key={basemap.id} className="space-y-2 border rounded-md p-3">
              <div className="flex items-center justify-between gap-4">
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
              {basemap.url.includes('{api_key}') && !envOnly && (
                <div className="flex items-center gap-2">
                  <Label className="text-xs shrink-0">{t('settings.basemaps.apiKeyLabel', 'API Key')}</Label>
                  <Input
                    type="password"
                    className="h-7 text-xs max-w-xs"
                    placeholder={basemap.api_key ? '••••••••' : t('settings.basemaps.apiKeyPlaceholder', 'Enter API key')}
                    defaultValue={basemap.api_key ?? ''}
                    onBlur={(e) => {
                      const val = e.target.value.trim();
                      if (val !== (basemap.api_key ?? '')) {
                        setters.basemaps(basemaps.map((b) => b.id === basemap.id ? { ...b, api_key: val || undefined } : b));
                      }
                    }}
                  />
                </div>
              )}
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
              <div className="space-y-1.5 max-w-md">
                <Label htmlFor="basemap-attribution">{t('settings.basemaps.attributionLabel', 'Attribution')}</Label>
                <Input
                  id="basemap-attribution"
                  placeholder={t('settings.basemaps.attributionPlaceholder', '\u00a9 Provider Name')}
                  value={newAttribution}
                  onChange={(e) => setNewAttribution(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">{t('settings.basemaps.attributionHelp', 'Optional. HTML allowed for links.')}</p>
              </div>
              <div className="space-y-1.5 max-w-md">
                <Label htmlFor="basemap-api-key">{t('settings.basemaps.apiKeyLabel', 'API Key')}</Label>
                <Input
                  id="basemap-api-key"
                  type="password"
                  placeholder={t('settings.basemaps.apiKeyPlaceholder', 'Optional — required if URL contains {api_key}')}
                  value={newApiKey}
                  onChange={(e) => setNewApiKey(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">{t('settings.basemaps.apiKeyHelp', 'Use {api_key} in the tile URL as a placeholder. The key is interpolated server-side.')}</p>
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

      <WidgetToggles
        settings={settings}
        enabledWidgets={values.enabled_widgets as string[]}
        onChangeEnabled={setters.enabled_widgets}
        onReset={onReset}
        envOnly={envOnly}
      />

      <SettingsFormActions dirty={dirty} hasDirty={hasDirty} envOnly={envOnly} isSaving={isSaving} onSave={onSave} onDiscard={discard} onDirtyChange={onDirtyChange} />
    </div>
  );
}
