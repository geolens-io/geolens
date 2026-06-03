import { paginationRange } from '@/lib/pagination';

describe('paginationRange', () => {
  it('computes correct range for first page', () => {
    const result = paginationRange(100, 0, 25);
    expect(result).toEqual({ skip: 0, totalPages: 4, rangeStart: 1, rangeEnd: 25 });
  });

  it('computes correct range for middle page', () => {
    const result = paginationRange(100, 2, 25);
    expect(result).toEqual({ skip: 50, totalPages: 4, rangeStart: 51, rangeEnd: 75 });
  });

  it('computes correct range for last page with remainder', () => {
    const result = paginationRange(30, 1, 25);
    expect(result).toEqual({ skip: 25, totalPages: 2, rangeStart: 26, rangeEnd: 30 });
  });

  it('returns zeros for total=0', () => {
    const result = paginationRange(0, 0, 25);
    expect(result).toEqual({ skip: 0, totalPages: 0, rangeStart: 0, rangeEnd: 0 });
  });

  it('handles single item', () => {
    const result = paginationRange(1, 0, 25);
    expect(result).toEqual({ skip: 0, totalPages: 1, rangeStart: 1, rangeEnd: 1 });
  });

  it('handles pageSize=1', () => {
    const result = paginationRange(5, 3, 1);
    expect(result).toEqual({ skip: 3, totalPages: 5, rangeStart: 4, rangeEnd: 4 });
  });

  it('handles page beyond total (out of range)', () => {
    const result = paginationRange(10, 5, 25);
    // skip=125 is beyond total=10, but the math still runs
    expect(result.skip).toBe(125);
    expect(result.totalPages).toBe(1);
  });
});
