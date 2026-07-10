import { namespaces, supportedLngs, fallbackLng } from '@/i18n/config';
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

/** Flatten to `key -> string value`, dropping non-string leaves. */
function flattenStrings(
  value: Record<string, unknown>,
  prefix = '',
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, nested] of Object.entries(value)) {
    const next = prefix ? `${prefix}.${key}` : key;
    if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
      Object.assign(out, flattenStrings(nested as Record<string, unknown>, next));
    } else if (typeof nested === 'string') {
      out[next] = nested;
    }
  }
  return out;
}

/**
 * Names of the `{{var}}` interpolations in a value, ignoring i18next formatting
 * suffixes: `{{count, number}}` and `{{count}}` are the same variable.
 */
function interpolationVars(value: string): string[] {
  return [...value.matchAll(/\{\{\s*([\w.]+)/g)].map((m) => m[1]).sort();
}

/**
 * Does this value contain translatable prose, as opposed to a proper noun, a
 * code sample, or a pure interpolation template?
 *
 * Interpolations are removed first, then we require at least two alphabetic
 * word tokens. This exempts `'{{currentPage}} / {{totalPages}}'` and `'CRS'`
 * while still covering `'Powered by GeoLens'`.
 */
function isProse(value: string): boolean {
  const withoutVars = value.replace(/\{\{[^}]*\}\}/g, ' ');
  const words = withoutVars.match(/[A-Za-zÀ-ÿ]{2,}/g) ?? [];
  return words.length >= 2;
}

/**
 * Keys whose value is *expected* to be byte-identical across every locale:
 * product names, standards names, technical abbreviations, code samples, and
 * input placeholders. Adding a key here is a deliberate act — it says "this
 * string is the same in Spanish, French, and German."
 *
 * Anything NOT in this list that matches English verbatim is an untranslated
 * string, and this suite fails.
 */
const IDENTICAL_ACROSS_LOCALES = new Set([
  // Product and standards names
  'common:enums.sourceFormat.arcgisFeatureServer', // ArcGIS FeatureServer
  'common:enums.sourceFormat.ogcapiFeatures', // OGC API Features
  'dataset:overview.ogcApiFeatures', // OGC API Features
  'common:adminNav.saml', // SAML SSO
  'admin:saml.title', // SAML SSO
  'admin:saml.enterpriseOnly.title', // SAML SSO

  // Technical abbreviations and axis labels
  'import:metadata.latLng', // Lat/Lng
  'dataset:metadata.crsSrid', // CRS / SRID
  'dataset:metadata.original', // original: EPSG:{{srid}}
  'builder:style.raster.stretchMinmax', // Min/Max
  'search:filters.bboxMinX', // Min X (West)
  'admin:saml.idpEntityId', // IdP Entity ID
  'admin:saml.spEntityId', // SP Entity ID
  'admin:saml.groupClaim', // Group Claim

  // Code samples and input placeholders
  'admin:settings.network.corsAllowedOriginsPlaceholder', // https://example.com, ...
  'builder:popup.expressionPlaceholder', // {city}, {state}
  'builder:share.iframeSandboxNote', // sandbox="allow-scripts" only — SEC-07 contract
  'dataset:schema.columnNamePlaceholder', // column_name
]);

const translatedLngs = supportedLngs.filter((lng) => lng !== fallbackLng);

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

  /**
   * fix(#438): I18N-01 — key parity above compares key *names* only. An English
   * value pasted verbatim into `de.json` shipped green, and the corpus was only
   * clean because a human swept it by hand (PRs #426/#428 were copy fixes, not
   * gate changes). This is the gate.
   */
  it('translates every prose value away from the English source', async () => {
    const resources = await loadAllResources();
    const untranslated: string[] = [];

    for (const ns of namespaces) {
      const english = flattenStrings(resources[fallbackLng][ns]);

      for (const lng of translatedLngs) {
        const localized = flattenStrings(resources[lng][ns]);

        for (const [key, englishValue] of Object.entries(english)) {
          if (IDENTICAL_ACROSS_LOCALES.has(`${ns}:${key}`)) continue;
          if (!isProse(englishValue)) continue;
          if (localized[key] === englishValue) {
            untranslated.push(`${lng}/${ns}.json → ${key}: ${JSON.stringify(englishValue)}`);
          }
        }
      }
    }

    expect(
      untranslated,
      'These values are byte-identical to English. Translate them, or — if the ' +
        'string is a proper noun, an abbreviation, or a code sample — add its ' +
        '`namespace:key` to IDENTICAL_ACROSS_LOCALES above.',
    ).toEqual([]);
  });

  /**
   * fix(#438): I18N-08 — a `{{count}}` → `{{n}}` typo in one locale used to ship
   * green and then render the raw `{{n}}` to the user at runtime.
   */
  it('keeps interpolation variables identical across locales', async () => {
    const resources = await loadAllResources();
    const mismatches: string[] = [];

    for (const ns of namespaces) {
      const english = flattenStrings(resources[fallbackLng][ns]);

      for (const lng of translatedLngs) {
        const localized = flattenStrings(resources[lng][ns]);

        for (const [key, englishValue] of Object.entries(english)) {
          const expected = interpolationVars(englishValue);
          const actual = interpolationVars(localized[key] ?? '');

          if (expected.join('|') !== actual.join('|')) {
            mismatches.push(
              `${lng}/${ns}.json → ${key}: expected {{${expected.join('}}, {{')}}}, ` +
                `got {{${actual.join('}}, {{')}}}`,
            );
          }
        }
      }
    }

    expect(mismatches).toEqual([]);
  });
});
