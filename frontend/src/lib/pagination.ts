/**
 * Compute pagination range values from total, page index, and page size.
 */
export function paginationRange(total: number, page: number, pageSize: number) {
  const skip = page * pageSize;
  return {
    skip,
    totalPages: Math.ceil(total / pageSize),
    rangeStart: total > 0 ? skip + 1 : 0,
    rangeEnd: Math.min(skip + pageSize, total),
  };
}
