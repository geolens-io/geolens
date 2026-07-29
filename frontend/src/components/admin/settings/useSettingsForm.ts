import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
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
  /** The save mutation's pending flag; lets the hook snapshot what was
   *  submitted so a post-submit edit survives the save's own refetch. */
  isSaving = false,
  /** The save mutation's error flag; a failed save acknowledged nothing,
   *  so the submitted snapshot is dropped as soon as this turns true. */
  saveFailed = false,
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset the draft only when the loaded settings change
  }, [settings]);

  // Per-field source ('default' | 'overridden' | 'env_only'), tracked so a
  // reset that removes an override without changing the effective value
  // (override value == default value) still counts as server movement.
  const serverSources = useMemo(() => {
    const src: Record<string, unknown> = {};
    for (const f of fields) {
      src[f.key] = findSetting(settings, f.key)?.source;
    }
    return src as Record<K, SettingItem['source'] | undefined>;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- recompute only when the loaded settings change
  }, [settings]);

  const [values, setValues] = useState<Values>(initialValues);

  const syncFromSettings = useCallback(() => {
    setValues(initialValues);
  }, [initialValues]);

  // Snapshot the draft the moment a save starts, so the save's own refetch
  // can tell an acknowledged submission apart from an edit typed while the
  // save was in flight (inputs stay enabled during isSaving).
  const valuesRef = useRef(values);
  valuesRef.current = values;
  const isSavingRef = useRef(isSaving);
  isSavingRef.current = isSaving;
  const submittedRef = useRef<Values | null>(null);
  useEffect(() => {
    if (isSaving) submittedRef.current = valuesRef.current;
  }, [isSaving]);

  // Snapshot lifetime rule: a SUCCESSFUL save always produces a settings
  // refetch, and that refetch can land after isSaving settles — so the
  // snapshot must stay armed across the pending→settled edge and is
  // consumed by the merge effect below. A FAILED save produces no
  // refetch and acknowledged nothing, so the snapshot is cleared the
  // moment the mutation reports an error; otherwise a later reset or
  // external change would be misread as a post-submit edit and the
  // stale draft would win over the new server value.
  useEffect(() => {
    if (saveFailed) submittedRef.current = null;
  }, [saveFailed]);

  // fix(#830): only sync untouched fields on refetch — a mid-edit query
  // invalidation (e.g. the semantic-search toggle) must not wipe drafts.
  // A field keeps its draft while the server state for it is unchanged.
  // When the refetch reports a NEW server value OR source for a field,
  // the server wins — covering save/reset refetches where the backend
  // canonicalized the submitted value (settings/router.py trims and
  // normalizes some values) and resets that only remove an override
  // whose value equals the default (only `source` moves) — so an
  // acknowledged save or reset reads pristine instead of staying dirty
  // forever — UNLESS the draft moved again after the save was
  // submitted, in which case the newer edit survives and stays dirty.
  const baselineRef = useRef(initialValues);
  const sourcesBaselineRef = useRef(serverSources);
  useEffect(() => {
    const prevBaseline = baselineRef.current;
    baselineRef.current = initialValues;
    const prevSources = sourcesBaselineRef.current;
    sourcesBaselineRef.current = serverSources;
    const submitted = submittedRef.current;
    // Consume the snapshot only once the save is no longer pending — an
    // unrelated refetch racing an in-flight save must leave it for the
    // save's own refetch.
    if (!isSavingRef.current) submittedRef.current = null;
    setValues((prev) => {
      const next: Record<string, unknown> = { ...initialValues };
      for (const f of fields) {
        const key = f.key as K;
        const mode = f.compare ?? 'strict';
        const touched = !isEqual(prev[key], prevBaseline[key], mode);
        if (!touched) continue;
        const serverChanged =
          !isEqual(initialValues[key], prevBaseline[key], mode) ||
          serverSources[key] !== prevSources[key];
        const editedAfterSubmit =
          submitted !== null && !isEqual(prev[key], submitted[key], mode);
        if (!serverChanged || editedAfterSubmit) {
          next[f.key] = prev[key];
        }
      }
      return next as Values;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resync only when the loaded settings change
  }, [initialValues]);

  const setters = useMemo(() => {
    const s: Record<string, (v: unknown) => void> = {};
    for (const f of fields) {
      s[f.key] = (v: unknown) =>
        setValues((prev) => ({ ...prev, [f.key]: v }));
    }
    return s as Record<K, (v: unknown) => void>;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once on mount
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
