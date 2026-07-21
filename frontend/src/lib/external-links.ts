export const GEOLENS_SITE_URL = 'https://getgeolens.com';
export const GEOLENS_GITHUB_URL = 'https://github.com/geolens-io/geolens';
export const GEOLENS_BUG_REPORT_URL = `${GEOLENS_GITHUB_URL}/issues/new?template=bug_report.yml`;
export const GEOLENS_DISCUSSIONS_URL = 'https://github.com/geolens-io/geolens/discussions';
export const GEOLENS_LICENSE_URL = 'https://github.com/geolens-io/geolens/blob/main/LICENSE';
export const GEOLENS_DOCS_URL = 'https://docs.getgeolens.com/';
// Privacy policy page — the page returns 404 today; it will be added in the marketing-site phase.
export const GEOLENS_PRIVACY_URL = 'https://getgeolens.com/privacy';

// Footer "API" link. Points at the canonical public API guide (always 200) rather
// than the instance's /api/docs Swagger, which 404s whenever interactive docs are
// disabled (ENVIRONMENT=production — the recommended self-host setting), so the
// footer link is live on every deployment including the demo.
export const GEOLENS_API_DOCS_URL = 'https://docs.getgeolens.com/guides/api/';
