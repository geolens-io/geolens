import i18n from 'i18next';

import { namespaces } from '@/i18n/config';
import { loadLocaleResources } from '@/i18n/resources';
import type { SupportedLng } from '@/i18n/config';

/**
 * Switches the running test i18next instance to `lng`, registering its
 * locale bundles first.
 *
 * A bare `i18n.changeLanguage(lng)`, or the app's own `changeAppLanguage`,
 * silently switches `i18n.language` without ever loading that locale's
 * strings under vitest, so `t()` keeps rendering English and a
 * locale-labelled assertion passes as long as English also satisfies it
 * (#1866). Two things combine to cause it:
 *
 * 1. `i18n.hasLoadedNamespace(ns, { lng })` reports a namespace as loaded
 *    through the `en` fallback chain even when `lng` was never added, so
 *    `changeAppLanguage`'s own `!hasLoadedNamespace(...)` guard never runs
 *    and it never calls `addResourceBundle`.
 * 2. The test i18next instance is initialized with the exact frozen object
 *    `src/i18n/resources.ts` exports (i18next stores the `resources` init
 *    option by reference, not by copy — see `ResourceStore`'s
 *    constructor). Registering a locale that was never in that object
 *    means adding a brand-new top-level key, which `Object.freeze` blocks
 *    even through `i18n.addResourceBundle`: it throws
 *    "Cannot add property <lng>, object is not extensible".
 *
 * This works around both: the first time a locale is requested, it
 * replaces the resource store's `data` with a shallow copy carrying an
 * empty, non-frozen placeholder for `lng`, so the write no longer touches
 * the frozen root. Every call after that lands through the ordinary
 * `addResourceBundle` path.
 */
export async function changeTestLanguage(lng: SupportedLng): Promise<void> {
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
