import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { getRampColors } from '../color-ramps';

// Ask AI's backend reads this fixture too (backend/tests/test_ai_ramp_parity.py).
const fixture = JSON.parse(
  readFileSync(resolve(__dirname, '../../../../backend/tests/fixtures/ramp_parity.json'), 'utf8'),
) as Record<string, Record<string, string[]>>;

describe('getRampColors parity fixture', () => {
  it.each(Object.entries(fixture))('%s', (ramp, byCount) => {
    for (const [count, colors] of Object.entries(byCount)) {
      expect(getRampColors(ramp, Number(count))).toEqual(colors);
    }
  });
});
