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

/** Starts a reset. A returned promise resolves true once the reset succeeded. */
export type ResetHandler = (key: string) => void | Promise<boolean>;

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
  /** The settings query's `dataUpdatedAt`. It advances on every completed
   *  fetch, including one that returns identical data and so leaves
   *  `settings` the same object, which still has to reconcile the draft. */
  settingsUpdatedAt?: number,
  /** The save mutation's error flag. A failed save does not acknowledge the
   *  drafts it submitted, so their edit markers outlive its error refetch. */
  saveFailed = false,
  /** The tab's reset handler; the returned `onReset` wraps it so a
   *  successful reset retires that field's edit markers. */
  submitReset?: ResetHandler,
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

  // Edits made once a save has started are recorded per field, tagged with
  // the number of the latest started save, so a refetch can tell an edit the
  // save acknowledged from one typed while it was in flight (inputs stay
  // enabled during isSaving). Recording setter calls rather than comparing
  // values keeps a refetched server value from being mistaken for an edit,
  // and catches an edit that lands back on the old value. An edit tagged n
  // was made after save n started, so it is submitted by save n + 1 and only
  // a refetch reflecting that later save retires it.
  const startedSaveRef = useRef(0);
  const settledSaveRef = useRef(0);
  const reflectedSaveRef = useRef(0);
  const editMarkersRef = useRef(new Map<string, number>());
  const editCountsRef = useRef(new Map<string, number>());
  const saveFailedRef = useRef(saveFailed);
  saveFailedRef.current = saveFailed;
  useEffect(() => {
    if (isSaving) startedSaveRef.current += 1;
    else if (!saveFailedRef.current) settledSaveRef.current = startedSaveRef.current;
  }, [isSaving]);

  // Discarding drops the draft, so edits recorded so far must not pin the
  // discarded value over the persisted one. Recording stays armed, because a
  // save that has settled may not have refetched yet and a new edit made
  // before it lands still has to survive it.
  const syncFromSettings = useCallback(() => {
    editMarkersRef.current.clear();
    setValues(initialValues);
  }, [initialValues]);

  // Tracking lifetime rule: a settings save refetches whether it succeeds
  // or fails (a failure can follow a partial commit), and that refetch can
  // land after isSaving settles — so recording stays armed across the
  // pending→settled edge until the merge effect below sees a refetch that
  // reflects a later save, which also runs on a refetch that returns
  // unchanged data. A refetch is taken to reflect every successful save that
  // had settled when it landed; a failed save acknowledges nothing, so its
  // markers last until a later successful save's refetch or a discard. Until
  // then an edited field stays dirty even when it equals the not-yet-refreshed
  // server value.

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
    const reflected = settledSaveRef.current;
    const markers = editMarkersRef.current;
    const editedDuringSave = new Set<string>();
    for (const [key, tag] of markers) {
      if (tag >= reflected) editedDuringSave.add(key);
    }
    // Later saves still owe their own refetch the edits recorded so far;
    // an unrelated refetch racing an in-flight save leaves them in place.
    if (startedSaveRef.current > reflected) {
      for (const [key, tag] of markers) {
        if (tag < reflected) markers.delete(key);
      }
    } else {
      markers.clear();
    }
    reflectedSaveRef.current = Math.max(reflectedSaveRef.current, reflected);
    setValues((prev) => {
      const next: Record<string, unknown> = { ...initialValues };
      for (const f of fields) {
        const key = f.key as K;
        const mode = f.compare ?? 'strict';
        // An edit made during the save is newer than anything the save
        // acknowledged, even when it lands back on the old baseline.
        if (editedDuringSave.has(f.key)) {
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
        editCountsRef.current.set(f.key, (editCountsRef.current.get(f.key) ?? 0) + 1);
        if (startedSaveRef.current > reflectedSaveRef.current) {
          editMarkersRef.current.set(f.key, startedSaveRef.current);
        }
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
        editMarkersRef.current.has(f.key) ||
        !isEqual(localVal, serverVal, f.compare ?? 'strict')
      ) {
        changes[f.key] = localVal;
      }
    }
    return changes;
  }, [fields, settings, values]);

  const hasDirty = Object.keys(dirty).length > 0;

  // A reset is acknowledged by its own refetch, which the save counters do
  // not track, so a successful reset retires the field's markers directly.
  // An edit made after the reset was submitted keeps its marker.
  const submitResetRef = useRef(submitReset);
  submitResetRef.current = submitReset;
  const onReset = useCallback((key: string) => {
    const submittedEdits = editCountsRef.current.get(key) ?? 0;
    return Promise.resolve(submitResetRef.current?.(key)).then((succeeded) => {
      if (succeeded === true && (editCountsRef.current.get(key) ?? 0) === submittedEdits) {
        editMarkersRef.current.delete(key);
      }
      return succeeded;
    });
  }, []);

  return { values, setters, dirty, hasDirty, discard: syncFromSettings, onReset };
}
