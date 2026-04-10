import { test } from '@playwright/test';

import { registerDemoSmokeSuite } from './demo-smoke-shared';

test.use({ storageState: { cookies: [], origins: [] } });

registerDemoSmokeSuite(test, 'themed-demo smoke (anonymous)');
