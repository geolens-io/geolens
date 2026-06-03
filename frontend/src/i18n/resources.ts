import { fallbackLng, namespaces, supportedLngs } from './config';
import type { Namespace, SupportedLng } from './config';

type ResourceMessages = Record<string, unknown>;
type LocaleResources = Record<Namespace, ResourceMessages>;
type I18nResources = Record<SupportedLng, LocaleResources>;

// Keep the fallback locale in the main bundle; other locales are lazy-loaded on demand.
const fallbackLocaleModules = import.meta.glob('./locales/en/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, ResourceMessages>;

const localeModuleLoaders = import.meta.glob('./locales/*/*.json', {
  import: 'default',
}) as Record<string, () => Promise<ResourceMessages>>;

const localeResourcesCache = new Map<SupportedLng, Promise<LocaleResources>>();

function getLocalePath(lng: SupportedLng, ns: Namespace): string {
  return `./locales/${lng}/${ns}.json`;
}

function getFallbackBundle(ns: Namespace): ResourceMessages {
  const path = `./locales/${fallbackLng}/${ns}.json`;
  const bundle = fallbackLocaleModules[path];

  if (!bundle) {
    throw new Error(`Missing i18n fallback bundle: ${path}`);
  }

  return bundle;
}

async function loadLocaleBundle(lng: SupportedLng, ns: Namespace): Promise<ResourceMessages> {
  if (lng === fallbackLng) {
    return getFallbackBundle(ns);
  }

  const path = getLocalePath(lng, ns);
  const loader = localeModuleLoaders[path];

  if (!loader) {
    throw new Error(`Missing i18n resource bundle: ${path}`);
  }

  return loader();
}

function getLocaleBundleSync(lng: SupportedLng, ns: Namespace): ResourceMessages {
  const path = `./locales/${lng}/${ns}.json`;
  const bundle = fallbackLocaleModules[path];

  if (!bundle) {
    throw new Error(`Missing i18n resource bundle: ${path}`);
  }

  return bundle;
}

export const resources = Object.freeze(
  {
    [fallbackLng]: Object.freeze(
      Object.fromEntries(
        namespaces.map((ns) => [ns, getLocaleBundleSync(fallbackLng, ns)]),
      ) as LocaleResources,
    ),
  } satisfies Partial<I18nResources>,
);

export async function loadLocaleResources(lng: SupportedLng): Promise<LocaleResources> {
  const cached = localeResourcesCache.get(lng);
  if (cached) {
    return cached;
  }

  const pending = Promise.all(
    namespaces.map(async (ns) => [ns, await loadLocaleBundle(lng, ns)] as const),
  ).then(
    (entries) =>
      Object.freeze(Object.fromEntries(entries) as LocaleResources),
  );

  localeResourcesCache.set(lng, pending);
  return pending;
}

export async function loadAllResources(): Promise<I18nResources> {
  const entries = await Promise.all(
    supportedLngs.map(async (lng) => [lng, await loadLocaleResources(lng)] as const),
  );

  return Object.freeze(Object.fromEntries(entries) as I18nResources);
}

export type { I18nResources, LocaleResources, ResourceMessages };
