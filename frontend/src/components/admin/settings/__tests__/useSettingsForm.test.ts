import { renderHook, act } from '@testing-library/react';
import { useSettingsForm } from '../useSettingsForm';
import type { SettingItem } from '@/api/settings';

function makeSetting(key: string, value: unknown): SettingItem {
  return { key, value, source: 'overridden', label: key };
}

describe('useSettingsForm', () => {
  describe('basic behavior', () => {
    it('initializes values from settings', () => {
      const settings = [makeSetting('name', 'Alice')];
      const fields = [{ key: 'name', defaultValue: '' }] as const;
      const { result } = renderHook(() => useSettingsForm(settings, fields));
      expect(result.current.values.name).toBe('Alice');
    });

    it('uses defaultValue when setting is missing', () => {
      const settings: SettingItem[] = [];
      const fields = [{ key: 'name', defaultValue: 'default' }] as const;
      const { result } = renderHook(() => useSettingsForm(settings, fields));
      expect(result.current.values.name).toBe('default');
    });

    it('tracks dirty state', () => {
      const settings = [makeSetting('name', 'Alice')];
      const fields = [{ key: 'name', defaultValue: '' }] as const;
      const { result } = renderHook(() => useSettingsForm(settings, fields));

      expect(result.current.hasDirty).toBe(false);

      act(() => {
        result.current.setters.name('Bob');
      });

      expect(result.current.hasDirty).toBe(true);
      expect(result.current.dirty).toEqual({ name: 'Bob' });
    });

    it('discard resets to server values', () => {
      const settings = [makeSetting('name', 'Alice')];
      const fields = [{ key: 'name', defaultValue: '' }] as const;
      const { result } = renderHook(() => useSettingsForm(settings, fields));

      act(() => result.current.setters.name('Bob'));
      expect(result.current.hasDirty).toBe(true);

      act(() => result.current.discard());
      expect(result.current.values.name).toBe('Alice');
      expect(result.current.hasDirty).toBe(false);
    });
  });

  describe('coerce option', () => {
    it('coerces server value for initialization', () => {
      const settings = [makeSetting('dims', 768)];
      const fields = [{ key: 'dims', defaultValue: '0', coerce: String }] as const;
      const { result } = renderHook(() => useSettingsForm(settings, fields));
      expect(result.current.values.dims).toBe('768');
    });

    it('coerces both sides for dirty comparison', () => {
      const settings = [makeSetting('dims', 768)];
      const fields = [{ key: 'dims', defaultValue: '0', coerce: String }] as const;
      const { result } = renderHook(() => useSettingsForm(settings, fields));

      // '768' === String(768) so not dirty
      expect(result.current.hasDirty).toBe(false);

      act(() => result.current.setters.dims('1024'));
      expect(result.current.hasDirty).toBe(true);
      expect(result.current.dirty).toEqual({ dims: '1024' });
    });

    it('coerce prevents false positive with number-to-string', () => {
      const settings = [makeSetting('count', 42)];
      const fields = [{ key: 'count', defaultValue: '0', coerce: String }] as const;
      const { result } = renderHook(() => useSettingsForm(settings, fields));

      // Without coerce, '42' !== 42 would be dirty. With coerce, both are '42'.
      expect(result.current.hasDirty).toBe(false);
    });
  });

  describe('compare option', () => {
    it('json compare detects deep equality', () => {
      const basemaps = [{ id: '1', enabled: true }];
      const settings = [makeSetting('basemaps', basemaps)];
      const fields = [{ key: 'basemaps', defaultValue: [], compare: 'json' as const }] as const;
      const { result } = renderHook(() => useSettingsForm(settings, fields));

      // Same content, different reference — not dirty because JSON compare
      expect(result.current.hasDirty).toBe(false);
    });

    it('json compare detects changes', () => {
      const basemaps = [{ id: '1', enabled: true }];
      const settings = [makeSetting('basemaps', basemaps)];
      const fields = [{ key: 'basemaps', defaultValue: [], compare: 'json' as const }] as const;
      const { result } = renderHook(() => useSettingsForm(settings, fields));

      act(() => {
        result.current.setters.basemaps([{ id: '1', enabled: false }]);
      });

      expect(result.current.hasDirty).toBe(true);
    });

    it('strict compare (default) treats objects as always different', () => {
      const obj = { a: 1 };
      const settings = [makeSetting('data', obj)];
      const fields = [{ key: 'data', defaultValue: {} }] as const;
      const { result } = renderHook(() => useSettingsForm(settings, fields));

      // Without json compare, the initial value from settings is the same reference
      // so it's not dirty
      expect(result.current.hasDirty).toBe(false);

      // But after setting a new object with same content, strict !== says dirty
      act(() => result.current.setters.data({ a: 1 }));
      expect(result.current.hasDirty).toBe(true);
    });
  });

  // fix(#830): a mid-edit settings refetch (new array identity) must not
  // wipe drafts or disarm the unsaved-changes guard.
  describe('refetch mid-edit', () => {
    const fields = [
      { key: 'name', defaultValue: '' },
      { key: 'flag', defaultValue: false },
    ] as const;

    type Props = { s: SettingItem[]; saving?: boolean };

    function renderWithSettings(settings: SettingItem[]) {
      return renderHook(
        ({ s, saving }: Props) => useSettingsForm(s, fields, saving),
        { initialProps: { s: settings } as Props },
      );
    }

    it('keeps dirty fields and the guard armed when an unrelated field refetches', () => {
      const { result, rerender } = renderWithSettings([
        makeSetting('name', 'Alice'),
        makeSetting('flag', false),
      ]);

      act(() => result.current.setters.name('Bob'));
      expect(result.current.hasDirty).toBe(true);

      // Simulate a query invalidation: new array identity, 'flag' changed
      // on the server (e.g. the semantic-search toggle), 'name' unchanged.
      rerender({ s: [makeSetting('name', 'Alice'), makeSetting('flag', true)] });

      expect(result.current.values.name).toBe('Bob'); // draft survives
      expect(result.current.values.flag).toBe(true); // untouched field syncs
      expect(result.current.hasDirty).toBe(true); // guard stays armed
      expect(result.current.dirty).toEqual({ name: 'Bob' });
    });

    it('keeps drafts across a refetch with identical content but new identity', () => {
      const { result, rerender } = renderWithSettings([
        makeSetting('name', 'Alice'),
        makeSetting('flag', false),
      ]);

      act(() => result.current.setters.name('Bob'));
      rerender({ s: [makeSetting('name', 'Alice'), makeSetting('flag', false)] });

      expect(result.current.values.name).toBe('Bob');
      expect(result.current.hasDirty).toBe(true);
    });

    it('reads pristine after a save lands (server now equals the draft)', () => {
      const { result, rerender } = renderWithSettings([
        makeSetting('name', 'Alice'),
        makeSetting('flag', false),
      ]);

      act(() => result.current.setters.name('Bob'));
      expect(result.current.hasDirty).toBe(true);

      // Save persisted the draft; the refetched settings now match it.
      rerender({ s: [makeSetting('name', 'Bob'), makeSetting('flag', false)] });

      expect(result.current.values.name).toBe('Bob');
      expect(result.current.hasDirty).toBe(false);
    });

    it('reads pristine when a save canonicalized the submitted value', () => {
      const { result, rerender } = renderWithSettings([
        makeSetting('name', 'Alice'),
        makeSetting('flag', false),
      ]);

      act(() => result.current.setters.name('  Bob  '));
      expect(result.current.hasDirty).toBe(true);

      // The backend trims/normalizes on save; the refetch returns the
      // canonical value, which differs from both the old baseline and
      // the draft. The server value must win or the form stays dirty
      // forever and a re-save repeats the request.
      rerender({ s: [makeSetting('name', 'Bob'), makeSetting('flag', false)] });

      expect(result.current.values.name).toBe('Bob');
      expect(result.current.hasDirty).toBe(false);
    });

    it('keeps an edit typed while the save was in flight', () => {
      const initial = [makeSetting('name', 'Alice'), makeSetting('flag', false)];
      const { result, rerender } = renderWithSettings(initial);

      act(() => result.current.setters.name('Bob'));

      // Save clicked: mutation goes pending with the draft 'Bob'. The
      // query data itself is unchanged (same identity) at this point.
      rerender({ s: initial, saving: true });

      // Inputs stay enabled while saving; the user keeps typing.
      act(() => result.current.setters.name('Carol'));

      // The save's refetch acknowledges 'Bob' — it must not clobber the
      // newer draft 'Carol' or silently mark the form pristine.
      rerender({ s: [makeSetting('name', 'Bob'), makeSetting('flag', false)], saving: false });

      expect(result.current.values.name).toBe('Carol');
      expect(result.current.hasDirty).toBe(true);
      expect(result.current.dirty).toEqual({ name: 'Carol' });
    });

    it('keeps a post-submit edit even when an unrelated refetch races the save', () => {
      const initial = [makeSetting('name', 'Alice'), makeSetting('flag', false)];
      const { result, rerender } = renderWithSettings(initial);

      act(() => result.current.setters.name('Bob'));
      rerender({ s: initial, saving: true });
      act(() => result.current.setters.name('Carol'));

      // An unrelated invalidation lands while the save is still pending —
      // it must not consume the submitted snapshot.
      rerender({ s: [makeSetting('name', 'Alice'), makeSetting('flag', true)], saving: true });
      expect(result.current.values.name).toBe('Carol');

      // Then the save's own refetch acknowledges 'Bob'.
      rerender({ s: [makeSetting('name', 'Bob'), makeSetting('flag', true)], saving: false });

      expect(result.current.values.name).toBe('Carol');
      expect(result.current.hasDirty).toBe(true);
    });

    it('reads pristine after a pending save when the draft was not edited again', () => {
      const initial = [makeSetting('name', 'Alice'), makeSetting('flag', false)];
      const { result, rerender } = renderWithSettings(initial);

      act(() => result.current.setters.name('  Bob  '));
      rerender({ s: initial, saving: true });

      // Refetch returns the canonicalized value for the acknowledged draft.
      rerender({ s: [makeSetting('name', 'Bob'), makeSetting('flag', false)], saving: false });

      expect(result.current.values.name).toBe('Bob');
      expect(result.current.hasDirty).toBe(false);
    });

    it('restores the server value when an edited field is reset', () => {
      const { result, rerender } = renderWithSettings([
        makeSetting('name', 'Alice'),
        makeSetting('flag', false),
      ]);

      act(() => result.current.setters.name('Bob'));

      // Reset on 'name' persisted the default; its refetched value changed,
      // so the stale draft is replaced by the authoritative server value.
      rerender({ s: [makeSetting('name', 'Default'), makeSetting('flag', false)] });

      expect(result.current.values.name).toBe('Default');
      expect(result.current.hasDirty).toBe(false);
    });

    it('resolves a concurrent change to the edited field as server-wins', () => {
      const { result, rerender } = renderWithSettings([
        makeSetting('name', 'Alice'),
        makeSetting('flag', false),
      ]);

      act(() => result.current.setters.name('Bob'));

      // Another admin changed 'name' underneath the edit: the field's
      // server value moved, so the server value replaces the draft.
      rerender({ s: [makeSetting('name', 'Carol'), makeSetting('flag', false)] });

      expect(result.current.values.name).toBe('Carol');
      expect(result.current.hasDirty).toBe(false);
    });

    it('keeps a json-compare draft through a refetch', () => {
      const jsonFields = [
        { key: 'basemaps', defaultValue: [], compare: 'json' as const },
        { key: 'flag', defaultValue: false },
      ] as const;
      const { result, rerender } = renderHook(
        ({ s }) => useSettingsForm(s, jsonFields),
        {
          initialProps: {
            s: [
              makeSetting('basemaps', [{ id: '1', enabled: true }]),
              makeSetting('flag', false),
            ],
          },
        },
      );

      act(() => result.current.setters.basemaps([{ id: '1', enabled: false }]));

      rerender({
        s: [
          makeSetting('basemaps', [{ id: '1', enabled: true }]),
          makeSetting('flag', true),
        ],
      });

      expect(result.current.values.basemaps).toEqual([{ id: '1', enabled: false }]);
      expect(result.current.values.flag).toBe(true);
      expect(result.current.hasDirty).toBe(true);
    });

    it('discard still resets all fields, including drafts, after a refetch', () => {
      const { result, rerender } = renderWithSettings([
        makeSetting('name', 'Alice'),
        makeSetting('flag', false),
      ]);

      act(() => result.current.setters.name('Bob'));
      rerender({ s: [makeSetting('name', 'Alice'), makeSetting('flag', true)] });

      act(() => result.current.discard());
      expect(result.current.values.name).toBe('Alice');
      expect(result.current.values.flag).toBe(true);
      expect(result.current.hasDirty).toBe(false);
    });
  });
});
