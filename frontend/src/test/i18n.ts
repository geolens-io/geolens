import i18n from 'i18next';

import { fallbackLng, namespaces } from '@/i18n/config';
import { loadLocaleResources } from '@/i18n/resources';
import type { SupportedLng } from '@/i18n/config';

/**
 * Switches the running test i18next instance to `lng`, loading that
 * locale's real bundles first.
 *
 * A bare `i18n.changeLanguage` switches `i18n.language` without loading the
 * target locale, so `t()` keeps rendering English. Use this, not
 * `changeAppLanguage` or a bare switch, in any test that switches language,
 * including back to English.
 */
export async function changeTestLanguage(lng: SupportedLng): Promise<void> {
  // The fallback locale's bundles are already loaded (and frozen); just switch.
  if (lng === fallbackLng) {
    await i18n.changeLanguage(lng);
    return;
  }

  const store = i18n.services.resourceStore;
  if (!store.data[lng]) {
    store.data = { ...store.data, [lng]: {} };
  }

  const localeResources = await loadLocaleResources(lng);
  for (const ns of namespaces) {
    i18n.addResourceBundle(lng, ns, localeResources[ns], true, true);
  }

  await i18n.changeLanguage(lng);
}
