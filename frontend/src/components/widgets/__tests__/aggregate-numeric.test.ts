import { isAggregateNumeric } from '@/lib/column-utils';

describe('isAggregateNumeric', () => {
  // backend/app/modules/catalog/datasets/domain/column_stats.py _NUMERIC_TYPES
  it.each(['smallint', 'integer', 'bigint', 'decimal', 'numeric', 'real', 'double precision', 'money'])(
    'reads %s as a number, as the aggregate endpoint does',
    (type) => {
      expect(isAggregateNumeric(type)).toBe(true);
      expect(isAggregateNumeric(type.toUpperCase())).toBe(true);
    },
  );

  it.each([
    'interval',
    'point',
    'text',
    'character varying',
    'boolean',
    'date',
    'timestamp with time zone',
    'json',
    'jsonb',
    'bytea',
    'user-defined',
    // Aliases information_schema never reports; the server would refuse them too.
    'int4',
    'float8',
  ])('refuses %s, which the endpoint would refuse', (type) => {
    expect(isAggregateNumeric(type)).toBe(false);
  });
});
