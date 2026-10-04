import { act } from '@testing-library/react';
import { changeTestLanguage } from '@/test/i18n';
import { renderHook } from '@/test/test-utils';
import { afterEach, describe, it, expect } from 'vitest';
import { useMapLocale } from '../use-map-locale';

describe('useMapLocale', () => {
  afterEach(async () => {
    await act(() => changeTestLanguage('en'));
  });

  it('keeps MapLibre control ids and translates every string', async () => {
    const english = renderHook(() => useMapLocale()).result.current;
    expect(english['NavigationControl.ZoomOut']).toBe('Zoom out');

    for (const lang of ['es', 'fr', 'de', 'zh'] as const) {
      await act(() => changeTestLanguage(lang));
      const locale = renderHook(() => useMapLocale()).result.current;
      expect(Object.keys(locale)).toEqual(Object.keys(english));
      for (const [key, value] of Object.entries(locale)) {
        expect(value, `${lang} ${key}`).not.toBe(english[key]);
      }
    }
  });

  it('returns the same object while the language is unchanged', () => {
    const { result, rerender } = renderHook(() => useMapLocale());
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});
