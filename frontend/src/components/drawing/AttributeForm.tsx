import { useState, useEffect, useMemo, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';

/** System columns that should never appear in the attribute form */
const SYSTEM_COLUMNS = new Set(['gid', 'geom', 'geom_4326']);

interface Column {
  name: string;
  type: string;
}

interface AttributeFormProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  columns: Column[];
  onSubmit: (properties: Record<string, unknown>) => void;
  onCancel: () => void;
  initialValues?: Record<string, unknown>;
}

function getInputType(colType: string): string {
  const t = colType.toLowerCase();
  if (t === 'integer' || t === 'bigint') return 'number-int';
  if (['double precision', 'real', 'numeric'].includes(t)) return 'number-float';
  if (t === 'boolean') return 'checkbox';
  if (t === 'date') return 'date';
  if (t === 'timestamp' || t === 'timestamptz' || t.startsWith('timestamp')) return 'datetime-local';
  return 'text';
}

function buildFormValues(
  editableColumns: Column[],
  initialValues?: Record<string, unknown>,
): Record<string, string | boolean> {
  const init: Record<string, string | boolean> = {};
  for (const col of editableColumns) {
    const inputType = getInputType(col.type);
    const initial = initialValues?.[col.name];
    if (initial !== undefined && initial !== null) {
      if (inputType === 'checkbox') {
        init[col.name] = Boolean(initial);
      } else {
        init[col.name] = String(initial);
      }
    } else {
      init[col.name] = inputType === 'checkbox' ? false : '';
    }
  }
  return init;
}

export function AttributeForm({
  open,
  onOpenChange,
  columns,
  onSubmit,
  onCancel,
  initialValues,
}: AttributeFormProps) {
  const { t } = useTranslation('builder');
  const editableColumns = useMemo(
    () => columns.filter((c) => !SYSTEM_COLUMNS.has(c.name)),
    [columns],
  );
  const isEditing = initialValues !== undefined;

  const [values, setValues] = useState<Record<string, string | boolean>>(() =>
    buildFormValues(editableColumns, initialValues),
  );

  // Re-populate form when initialValues changes (different feature selected)
  useEffect(() => {
    setValues(buildFormValues(editableColumns, initialValues));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialValues]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const properties: Record<string, unknown> = {};
    for (const col of editableColumns) {
      const raw = values[col.name];
      const inputType = getInputType(col.type);
      if (inputType === 'checkbox') {
        properties[col.name] = raw === true;
      } else if (inputType === 'number-int' || inputType === 'number-float') {
        const str = raw as string;
        properties[col.name] = str === '' ? null : Number(str);
      } else {
        const str = raw as string;
        properties[col.name] = str === '' ? null : str;
      }
    }
    onSubmit(properties);
  }

  function handleSkip() {
    onSubmit({});
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEditing ? t('attributeForm.titleEdit') : t('attributeForm.titleNew')}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? t('attributeForm.descriptionEdit')
              : t('attributeForm.descriptionNew')}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {editableColumns.map((col) => {
            const inputType = getInputType(col.type);

            if (inputType === 'checkbox') {
              return (
                <div key={col.name} className="flex items-center gap-2">
                  <Checkbox
                    id={`attr-${col.name}`}
                    checked={values[col.name] === true}
                    onCheckedChange={(checked) =>
                      setValues((v) => ({ ...v, [col.name]: checked === true }))
                    }
                  />
                  <Label htmlFor={`attr-${col.name}`}>{col.name}</Label>
                </div>
              );
            }

            const htmlType =
              inputType === 'number-int' || inputType === 'number-float'
                ? 'number'
                : inputType;

            return (
              <div key={col.name} className="space-y-2">
                <Label htmlFor={`attr-${col.name}`}>{col.name}</Label>
                <Input
                  id={`attr-${col.name}`}
                  type={htmlType}
                  step={inputType === 'number-int' ? '1' : inputType === 'number-float' ? 'any' : undefined}
                  value={values[col.name] as string}
                  onChange={(e) =>
                    setValues((v) => ({ ...v, [col.name]: e.target.value }))
                  }
                />
              </div>
            );
          })}

          <DialogFooter>
            {!isEditing && (
              <Button type="button" variant="outline" onClick={handleSkip}>
                {t('attributeForm.skip')}
              </Button>
            )}
            <Button type="button" variant="ghost" onClick={onCancel}>
              {t('common:cancel')}
            </Button>
            <Button type="submit">{t('common:save')}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
