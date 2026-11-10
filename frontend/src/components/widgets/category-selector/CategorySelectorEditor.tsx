import { useTranslation } from 'react-i18next';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import type { WidgetEditorProps } from '../contract';
import { ColumnField } from '../editor-fields';
import type { CategorySelectorConfig } from './definition';

export default function CategorySelectorEditor({
  config,
  onChange,
  columns,
  idPrefix,
}: WidgetEditorProps<CategorySelectorConfig>) {
  const { t } = useTranslation('widgets');
  return (
    <div className="space-y-3">
      <ColumnField
        id={`${idPrefix}-column`}
        label={t('editor.column')}
        value={config.column}
        columns={columns}
        onChange={(column) => onChange({ ...config, column })}
      />
      <div className="flex items-center gap-2">
        <Checkbox
          id={`${idPrefix}-multiple`}
          checked={config.multiple}
          onCheckedChange={(checked) => onChange({ ...config, multiple: checked === true })}
        />
        <Label className="text-xs font-normal" htmlFor={`${idPrefix}-multiple`}>
          {t('editor.multiple')}
        </Label>
      </div>
    </div>
  );
}
