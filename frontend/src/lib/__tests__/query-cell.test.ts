import { formatQueryCell } from '@/lib/query-cell';

function sumOfTenths(count: number): number {
  let total = 0;
  for (let i = 0; i < count; i++) total += 0.1;
  return total;
}

describe('formatQueryCell', () => {
  it.each([
    [491.9000000000001, '491.9'],
    [0.1 + 0.2, '0.3'],
    [99.99999999999999, '100'],
    [sumOfTenths(100), '10'],
    [sumOfTenths(262), '26.2'],
    [sumOfTenths(928), '92.8'],
    [7708611.570000037, '7708611.57'],
    [884256.9359999986, '884256.936'],
    [-12.300000000000004, '-12.3'],
    [3.0000000000000004e-7, '3e-7'],
  ])('drops the rounding noise in %s', (raw, shown) => {
    expect(formatQueryCell(raw)).toBe(shown);
  });

  it.each([
    [2.0000001, '2.0000001'],
    [3.14159, '3.14159'],
    [1e-7, '1e-7'],
    [1234567890123456, '1234567890123456'],
    [9007199254740992, '9007199254740992'],
    [1.2000000000000003e21, '1.2000000000000003e+21'],
  ])('leaves %s as it is', (raw, shown) => {
    expect(formatQueryCell(raw)).toBe(shown);
  });

  it('shows a value past 12 significant digits at 12', () => {
    expect(formatQueryCell(40.712775891234)).toBe('40.7127758912');
  });

  it('passes non-numbers through and blanks missing values', () => {
    expect(formatQueryCell('0.30000000000000004')).toBe('0.30000000000000004');
    expect(formatQueryCell(null)).toBe('');
    expect(formatQueryCell(undefined)).toBe('');
  });
});
