import { useState, useEffect, useCallback, useMemo } from 'react';
import { findSetting } from './utils';
import type { SettingItem } from '@/api/settings';

type FieldDef = {
  key: string;
  defaultValue: unknown;
};

/**
 * Manages settings form state: syncs from server settings, tracks dirty fields,
 * and provides save/discard helpers.
 *
 * Usage:
 *   const { values, setters, dirty, hasDirty, discard } = useSettingsForm(settings, [
 *     { key: 'cors_allowed_origins', defaultValue: '' },
 *   ]);
 *   // values.cors_allowed_origins, setters.cors_allowed_origins(newVal), etc.
 */
export function useSettingsForm<K extends string>(
  settings: SettingItem[],
  fields: readonly FieldDef[] & { readonly [i: number]: { key: K } },
) {
  type Values = Record<K, unknown>;

  const initialValues = useMemo(() => {
    const vals: Record<string, unknown> = {};
    for (const f of fields) {
      const setting = findSetting(settings, f.key);
      vals[f.key] = setting ? setting.value : f.defaultValue;
    }
    return vals as Values;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings]);

  const [values, setValues] = useState<Values>(initialValues);

  const syncFromSettings = useCallback(() => {
    setValues(initialValues);
  }, [initialValues]);

  useEffect(() => {
    syncFromSettings();
  }, [syncFromSettings]);

  const setters = useMemo(() => {
    const s: Record<string, (v: unknown) => void> = {};
    for (const f of fields) {
      s[f.key] = (v: unknown) =>
        setValues((prev) => ({ ...prev, [f.key]: v }));
    }
    return s as Record<K, (v: unknown) => void>;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty = useMemo(() => {
    const changes: Record<string, unknown> = {};
    for (const f of fields) {
      const setting = findSetting(settings, f.key);
      if (setting && values[f.key as K] !== setting.value) {
        changes[f.key] = values[f.key as K];
      }
    }
    return changes;
  }, [fields, settings, values]);

  const hasDirty = Object.keys(dirty).length > 0;

  return { values, setters, dirty, hasDirty, discard: syncFromSettings };
}
