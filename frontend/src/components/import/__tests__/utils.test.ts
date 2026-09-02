/**
 * codex review #1757: defaultPortalFor's three cases. Prefilling the
 * service URL's own origin (the previous behavior) presented
 * services6.arcgis.com and similar ArcGIS Online feature-service hosts as a
 * valid sign-in portal, when the actual portal is www.arcgis.com; sign-in
 * against the untouched default then failed. See utils.ts for the full
 * reasoning per case.
 */
import { defaultPortalFor } from '../utils';

describe('defaultPortalFor', () => {
  it('prefills www.arcgis.com for an ArcGIS Online service host that is not *.maps.arcgis.com', () => {
    expect(
      defaultPortalFor(
        'https://services6.arcgis.com/abcd1234/arcgis/rest/services/Foo/FeatureServer',
      ),
    ).toBe('https://www.arcgis.com');
  });

  it("prefills the host's own origin for a *.maps.arcgis.com portal-shaped host", () => {
    expect(
      defaultPortalFor(
        'https://myorg.maps.arcgis.com/arcgis/rest/services/Foo/FeatureServer',
      ),
    ).toBe('https://myorg.maps.arcgis.com');
  });

  it('leaves the field empty for an Enterprise host with no derivable portal', () => {
    expect(
      defaultPortalFor('https://gis.example-city.gov/server/rest/services/Foo/FeatureServer'),
    ).toBe('');
  });
});
