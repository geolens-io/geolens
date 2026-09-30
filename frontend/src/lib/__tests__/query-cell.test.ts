import { formatQueryCell } from '@/lib/query-cell';

function sumOfTenths(count: number): number {
  let total = 0;
  for (let i = 0; i < count; i++) total += 0.1;
  return total;
}

describe('formatQueryCell', () => {
  it.each([
    [491.9000000000001, '491.9'],
    [56.025000000000006, '56.025'],
    [0.1 + 0.2, '0.3'],
    [99.99999999999999, '100'],
    [sumOfTenths(100), '10'],
    [-12.300000000000004, '-12.3'],
    [3.0000000000000004e-7, '3e-7'],
    [1.2000000000000003e21, '1.2e+21'],
  ])('rounds the noise tail of %s', (raw, shown) => {
    expect(formatQueryCell(raw)).toBe(shown);
  });

  it.each([
    [100000000000000.5, '100000000000000.5'],
    [2.0000001, '2.0000001'],
    [1234567890123456, '1234567890123456'],
    [3.14159, '3.14159'],
    [1e-7, '1e-7'],
  ])('leaves %s as it is', (raw, shown) => {
    expect(formatQueryCell(raw)).toBe(shown);
  });

  it('passes non-numbers through and blanks missing values', () => {
    expect(formatQueryCell('0.30000000000000004')).toBe('0.30000000000000004');
    expect(formatQueryCell(null)).toBe('');
    expect(formatQueryCell(undefined)).toBe('');
  });
});
