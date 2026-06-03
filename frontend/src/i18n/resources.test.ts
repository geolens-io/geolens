import { namespaces, supportedLngs } from '@/i18n/config';
import { loadAllResources } from '@/i18n/resources';

function flattenKeys(value: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, nested]) => {
    const next = prefix ? `${prefix}.${key}` : key;

    if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
      return flattenKeys(nested as Record<string, unknown>, next);
    }

    return [next];
  });
}

describe('i18n resources', () => {
  it('ships every configured namespace for every supported language', async () => {
    const resources = await loadAllResources();

    for (const lng of supportedLngs) {
      expect(Object.keys(resources[lng]).sort()).toEqual([...namespaces].sort());
    }
  });

  it('keeps locale key parity with the English fallback bundles', async () => {
    const resources = await loadAllResources();

    for (const ns of namespaces) {
      const englishKeys = flattenKeys(resources.en[ns]).sort();

      for (const lng of supportedLngs) {
        expect(flattenKeys(resources[lng][ns]).sort()).toEqual(englishKeys);
      }
    }
  });
});
