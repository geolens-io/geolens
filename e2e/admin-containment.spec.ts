import { test, expect } from './helpers/session';

const PAGES = [
  { name: 'users', path: '/admin/users', heading: 'Users' },
  { name: 'jobs', path: '/admin/jobs', heading: 'Jobs' },
  { name: 'audit', path: '/admin/audit', heading: 'Audit Log' },
  { name: 'SAML', path: '/admin/saml', heading: 'SAML SSO' },
];
const WIDTHS = [320, 768, 1024];

test.describe('admin pages stay inside the viewport', () => {
  for (const { name, path, heading } of PAGES) {
    for (const width of WIDTHS) {
      test(`${name} page at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 800 });
        await page.goto(path);
        await expect(page.getByRole('heading', { level: 1, name: heading, exact: true })).toBeVisible({
          timeout: 15_000,
        });
        await page.waitForLoadState('networkidle');

        const { scrollWidth, clientWidth } = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
        }));
        expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
      });
    }
  }
});
