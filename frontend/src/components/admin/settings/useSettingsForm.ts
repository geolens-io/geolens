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
  /** The save mutation's pending flag; lets the hook track edits made after
   *  the submit so they survive the save's own refetch. */
  isSaving = false,
  /** The save mutation's error flag; a failed save acknowledged nothing,
   *  so edits made during it stop counting as unsaved once this turns true. */
  saveFailed = false,
  /** The settings query's `dataUpdatedAt`. It advances on every completed
   *  fetch, including one that returns identical data and so leaves
   *  `settings` the same object, which still has to reconcile the draft. */
  settingsUpdatedAt?: number,
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

  // Track which fields the user edits once a save starts, so the save's own
  // refetch can tell an acknowledged submission apart from an edit typed
  // while the save was in flight (inputs stay enabled during isSaving).
  // Recording setter calls rather than comparing values keeps a refetched
  // server value from being mistaken for an edit, and catches an edit that
  // lands back on the old value. Null means no save is being tracked.
  const isSavingRef = useRef(isSaving);
  isSavingRef.current = isSaving;
  const editedDuringSaveRef = useRef<Set<string> | null>(null);
  const trackingFailedRef = useRef(false);
  useEffect(() => {
    if (!isSaving) return;
    editedDuringSaveRef.current = new Set();
    trackingFailedRef.current = false;
  }, [isSaving]);

  // Discarding drops the draft, so edits tracked so far must not pin the
  // discarded value over the persisted one. Tracking stays armed, because a
  // save that has settled may not have refetched yet and a new edit made
  // before it lands still has to survive it.
  const syncFromSettings = useCallback(() => {
    if (editedDuringSaveRef.current) editedDuringSaveRef.current = new Set();
    setValues(initialValues);
  }, [initialValues]);

  // Tracking lifetime rule: a settings save refetches whether it succeeds
  // or fails (a failure can follow a partial commit), and that refetch can
  // land after isSaving settles — so tracking stays armed across the
  // pending→settled edge and is consumed by the merge effect below. A failed
  // save acknowledged nothing, so its tracking only shields the draft from
  // that refetch: it no longer holds a field dirty, so an edit that went back
  // to the server value reads clean. `dirty` reads the flag, so flipping it
  // recomputes `dirty`.
  const [trackingVersion, setTrackingVersion] = useState(0);
  useEffect(() => {
    if (!saveFailed) return;
    trackingFailedRef.current = true;
    setTrackingVersion((v) => v + 1);
  }, [saveFailed]);

  // fix(#830): only sync untouched fields on refetch — a mid-edit query
  // invalidation (e.g. a background refetch) must not wipe drafts.
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
    const editedDuringSave = editedDuringSaveRef.current;
    // Consume the tracking only once the save is no longer pending — an
    // unrelated refetch racing an in-flight save must leave it for the
    // save's own refetch.
    if (!isSavingRef.current) editedDuringSaveRef.current = null;
    setValues((prev) => {
      const next: Record<string, unknown> = { ...initialValues };
      for (const f of fields) {
        const key = f.key as K;
        const mode = f.compare ?? 'strict';
        // An edit made during the save is newer than anything the save
        // acknowledged, even when it lands back on the old baseline.
        if (editedDuringSave?.has(f.key)) {
          next[f.key] = prev[key];
          continue;
        }
        const touched = !isEqual(prev[key], prevBaseline[key], mode);
        if (!touched) continue;
        const serverChanged =
          !isEqual(initialValues[key], prevBaseline[key], mode) ||
          serverSources[key] !== prevSources[key];
        if (!serverChanged) {
          next[f.key] = prev[key];
        }
      }
      return next as Values;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resync only when the loaded settings change
  }, [initialValues, settingsUpdatedAt]);

  const setters = useMemo(() => {
    const s: Record<string, (v: unknown) => void> = {};
    for (const f of fields) {
      s[f.key] = (v: unknown) => {
        editedDuringSaveRef.current?.add(f.key);
        setValues((prev) => ({ ...prev, [f.key]: v }));
      };
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
      // A field edited during a save stays dirty until the save's refetch
      // lands, even when it equals the not-yet-refreshed server value, so
      // the navigation guard and Save still see it.
      if (
        (editedDuringSaveRef.current?.has(f.key) && !trackingFailedRef.current) ||
        !isEqual(localVal, serverVal, f.compare ?? 'strict')
      ) {
        changes[f.key] = localVal;
      }
    }
    return changes;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- trackingVersion recomputes dirty when edit tracking is cleared
  }, [fields, settings, values, trackingVersion]);

  const hasDirty = Object.keys(dirty).length > 0;

  return { values, setters, dirty, hasDirty, discard: syncFromSettings };
}
