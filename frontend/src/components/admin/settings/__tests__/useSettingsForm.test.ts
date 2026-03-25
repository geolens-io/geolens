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
});
