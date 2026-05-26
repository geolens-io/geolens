import { test } from '@playwright/test';

import { registerShowcaseSmokeSuite } from './showcase-smoke-shared';

registerShowcaseSmokeSuite(test, 'showcase-map smoke');
