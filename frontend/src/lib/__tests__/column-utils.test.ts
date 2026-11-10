import { isNumericColumn } from '@/lib/column-utils';

describe('isNumericColumn', () => {
  it.each(['integer', 'bigint', 'smallint', 'numeric', 'real', 'double precision', 'INTEGER', 'int4', 'float8'])(
    'reads %s as numeric',
    (type) => {
      expect(isNumericColumn(type)).toBe(true);
    },
  );

  // Types whose names contain a numeric type's name.
  it.each(['interval', 'point', 'character varying', 'timestamp with time zone', 'user-defined'])(
    'refuses %s',
    (type) => {
      expect(isNumericColumn(type)).toBe(false);
    },
  );
});
