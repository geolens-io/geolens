import { useTranslation } from 'react-i18next';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { isAggregateNumeric } from '@/lib/column-utils';
import type { Statistic } from './aggregate';
import type { WidgetColumn } from './contract';

const STAT_NAME_KEYS = {
  count: 'editor.statNames.count',
  sum: 'editor.statNames.sum',
  mean: 'editor.statNames.mean',
  min: 'editor.statNames.min',
  max: 'editor.statNames.max',
} as const satisfies Record<Statistic, string>;
const STATISTICS = Object.keys(STAT_NAME_KEYS) as Statistic[];

interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

/** A labelled select. A value that isn't among the options shows the placeholder. */
export function SelectField({
  id,
  label,
  value,
  options,
  placeholder,
  onChange,
}: {
  id: string;
  label: string;
  value: string | null;
  options: readonly SelectOption[];
  placeholder?: string;
  onChange: (value: string) => void;
}) {
  const known = options.some((option) => option.value === value);
  return (
    <div className="space-y-1.5">
      <Label className="text-xs" htmlFor={id}>
        {label}
      </Label>
      <Select value={known ? (value ?? '') : ''} onValueChange={onChange}>
        <SelectTrigger id={id} size="sm" className="w-full">
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/** A select of the layer's columns. A stored column the layer no longer has shows the placeholder. */
export function ColumnField({
  id,
  label,
  value,
  columns,
  onChange,
}: {
  id: string;
  label: string;
  value: string | null;
  columns: readonly WidgetColumn[];
  onChange: (column: string) => void;
}) {
  const { t } = useTranslation('widgets');
  return (
    <SelectField
      id={id}
      label={label}
      value={value}
      options={columns.map((column) => ({ value: column.name, label: column.name }))}
      placeholder={t('editor.pickColumn')}
      onChange={onChange}
    />
  );
}

/**
 * A statistic and the numeric column it reads. Count reads no column; any
 * other statistic keeps the current column when it's numeric, else takes the
 * layer's first numeric one, and is offered only when the layer has one.
 */
export function StatColumnFields({
  idPrefix,
  stat,
  column,
  columns,
  onChange,
}: {
  idPrefix: string;
  stat: Statistic;
  column: string | null;
  columns: readonly WidgetColumn[];
  onChange: (stat: Statistic, column: string | null) => void;
}) {
  const { t } = useTranslation('widgets');
  const numeric = columns.filter((candidate) => isAggregateNumeric(candidate.type));
  const columnFor = (next: Statistic) =>
    next === 'count'
      ? null
      : numeric.some((candidate) => candidate.name === column)
        ? column
        : (numeric[0]?.name ?? null);
  return (
    <>
      <SelectField
        id={`${idPrefix}-stat`}
        label={t('editor.stat')}
        value={stat}
        options={STATISTICS.map((option) => ({
          value: option,
          label: t(STAT_NAME_KEYS[option]),
          disabled: option !== 'count' && numeric.length === 0,
        }))}
        onChange={(next) => onChange(next as Statistic, columnFor(next as Statistic))}
      />
      {numeric.length === 0 && (
        <p className="text-xs text-muted-foreground">{t('editor.noNumericColumns')}</p>
      )}
      {stat !== 'count' && (
        <ColumnField
          id={`${idPrefix}-stat-column`}
          label={t('editor.column')}
          value={column}
          columns={numeric}
          onChange={(next) => onChange(stat, next)}
        />
      )}
    </>
  );
}
