import { test } from '@playwright/test';

import { registerDemoSmokeSuite } from './demo-smoke-shared';

registerDemoSmokeSuite(test, 'themed-demo smoke');
