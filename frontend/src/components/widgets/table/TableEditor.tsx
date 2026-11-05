import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import type { WidgetEditorProps } from '../contract';
import { ColumnField, IntegerField, SelectField, STAT_NAME_KEYS, StatColumnFields } from '../editor-fields';
import { MAX_TABLE_ROWS, MAX_TABLE_STATS, type TableConfig } from './definition';

const GROUP = 'group';

export default function TableEditor({ config, onChange, columns, idPrefix }: WidgetEditorProps<TableConfig>) {
  const { t } = useTranslation('widgets');
  const { stats } = config;
  const setStats = (next: TableConfig['stats'], sortBy = config.sort_by) =>
    onChange({ ...config, stats: next, sort_by: sortBy !== null && sortBy >= next.length ? null : sortBy });
  return (
    <div className="space-y-3">
      <ColumnField
        id={`${idPrefix}-group`}
        label={t('editor.groupBy')}
        value={config.group_column}
        columns={columns}
        onChange={(group_column) => onChange({ ...config, group_column })}
      />
      {stats.map((entry, index) => (
        <fieldset key={index} className="space-y-2 rounded-md border p-2">
          <legend className="px-1 text-xs font-medium">{t('editor.statN', { n: index + 1 })}</legend>
          <StatColumnFields
            idPrefix={`${idPrefix}-stat-${index}`}
            stat={entry.stat}
            column={entry.column}
            columns={columns}
            onChange={(stat, column) => setStats(stats.map((old, i) => (i === index ? { stat, column } : old)))}
          />
          {stats.length > 1 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                const sortBy = config.sort_by;
                // Removing the sorted statistic falls back to the group; later ones shift down.
                const shifted = sortBy === null || sortBy === index ? null : sortBy > index ? sortBy - 1 : sortBy;
                setStats(
                  stats.filter((_, i) => i !== index),
                  shifted,
                );
              }}
            >
              {t('editor.removeStat', { n: index + 1 })}
            </Button>
          )}
        </fieldset>
      ))}
      {stats.length < MAX_TABLE_STATS && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setStats([...stats, { stat: 'count', column: null }])}
        >
          {t('editor.addStat')}
        </Button>
      )}
      <SelectField
        id={`${idPrefix}-sort-by`}
        label={t('editor.sortBy')}
        value={config.sort_by === null ? GROUP : String(config.sort_by)}
        options={[
          { value: GROUP, label: t('editor.sortGroup') },
          ...stats.map((entry, index) => ({
            value: String(index),
            label: t('editor.statN', { n: index + 1 }) + ': ' + t(STAT_NAME_KEYS[entry.stat]) + (entry.column ? ` (${entry.column})` : ''),
          })),
        ]}
        onChange={(value) => onChange({ ...config, sort_by: value === GROUP ? null : Number(value) })}
      />
      <SelectField
        id={`${idPrefix}-sort`}
        label={t('editor.sortDirection')}
        value={config.sort}
        options={[
          { value: 'desc', label: t('editor.sortDesc') },
          { value: 'asc', label: t('editor.sortAsc') },
        ]}
        onChange={(sort) => onChange({ ...config, sort: sort as TableConfig['sort'] })}
      />
      <IntegerField
        id={`${idPrefix}-limit`}
        label={t('editor.rows')}
        value={config.limit}
        min={1}
        max={MAX_TABLE_ROWS}
        onChange={(limit) => onChange({ ...config, limit })}
      />
    </div>
  );
}
