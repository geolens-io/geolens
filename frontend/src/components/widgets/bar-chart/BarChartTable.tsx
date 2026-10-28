import { useTranslation } from 'react-i18next';
import type { BarChartConfig } from './definition';
import type { BarChartText } from './bar-chart-rows';

/** The chart's data as a table: its text alternative. */
export function BarChartTable({ config, text }: { config: BarChartConfig; text: BarChartText }) {
  const { t } = useTranslation('widgets');
  if (!text.rows || text.rows.length === 0) {
    return <p className="text-sm text-muted-foreground">{t(text.rows ? 'noRows' : 'noData')}</p>;
  }
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">{text.summary}</caption>
      <thead>
        <tr className="border-b text-left">
          <th scope="col" className="py-1 pr-2 font-medium">
            {config.column}
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            {text.valueHeader}
          </th>
        </tr>
      </thead>
      <tbody>
        {text.rows.map((row, index) => (
          <tr key={index} className="border-b last:border-0">
            <th scope="row" className="py-1 pr-2 text-left font-normal break-words">
              {row.label}
            </th>
            <td className="py-1 text-right tabular-nums">{row.text}</td>
          </tr>
        ))}
        {text.other !== undefined && (
          <tr>
            <th scope="row" className="py-1 pr-2 text-left font-normal text-muted-foreground">
              {t('types.bar_chart.other')}
            </th>
            <td className="py-1 text-right tabular-nums text-muted-foreground">{text.other}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
