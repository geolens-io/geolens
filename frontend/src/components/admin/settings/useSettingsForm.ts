import { useState, useEffect, useCallback, useMemo } from 'react';
import { findSetting } from './utils';
import type { SettingItem } from '@/api/settings';

type FieldDef = {
  key: string;
  defaultValue: unknown;
  /** Coerce server and local values before comparison and on initial sync.
   *  e.g. `String` to compare a numeric server value with a string input. */
  coerce?: (v: unknown) => unknown;
  /** Comparison strategy: 'strict' (===, default) or 'json' (deep equality). */
  compare?: 'strict' | 'json';
};

function isEqual(a: unknown, b: unknown, mode: 'strict' | 'json' = 'strict'): boolean {
  if (mode === 'json') return JSON.stringify(a) === JSON.stringify(b);
  return a === b;
}

/**
 * Manages settings form state: syncs from server settings, tracks dirty fields,
 * and provides save/discard helpers.
 *
 * Usage:
 *   const { values, setters, dirty, hasDirty, discard } = useSettingsForm(settings, [
 *     { key: 'cors_allowed_origins', defaultValue: '' },
 *     { key: 'embedding_dims', defaultValue: 0, coerce: String },
 *     { key: 'basemaps', defaultValue: [], compare: 'json' },
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
      const raw = setting ? setting.value : f.defaultValue;
      vals[f.key] = f.coerce ? f.coerce(raw) : raw;
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
      if (!setting) continue;
      const serverVal = f.coerce ? f.coerce(setting.value) : setting.value;
      const localVal = values[f.key as K];
      if (!isEqual(localVal, serverVal, f.compare ?? 'strict')) {
        changes[f.key] = localVal;
      }
    }
    return changes;
  }, [fields, settings, values]);

  const hasDirty = Object.keys(dirty).length > 0;

  return { values, setters, dirty, hasDirty, discard: syncFromSettings };
}
