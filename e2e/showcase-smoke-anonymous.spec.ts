import { test } from '@playwright/test';

import { registerShowcaseSmokeSuite } from './showcase-smoke-shared';

test.use({ storageState: { cookies: [], origins: [] } });

registerShowcaseSmokeSuite(test, 'showcase-map smoke (anonymous)');
