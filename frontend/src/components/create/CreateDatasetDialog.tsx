import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Loader2, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useCreateDataset } from '@/components/dataset/hooks/use-dataset';

type ColumnType = 'text' | 'integer' | 'float' | 'date' | 'boolean';

interface ColumnRow {
  id: number;
  name: string;
  type: ColumnType;
}

let nextId = 1;

function createEmptyColumn(): ColumnRow {
  return { id: nextId++, name: '', type: 'text' };
}

interface CreateDatasetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateDatasetDialog({ open, onOpenChange }: CreateDatasetDialogProps) {
  const { t } = useTranslation('search');
  const navigate = useNavigate();
  const createMutation = useCreateDataset();
  const [title, setTitle] = useState('');
  const [columns, setColumns] = useState<ColumnRow[]>(() => [createEmptyColumn()]);

  const typeOptions: { value: ColumnType; label: string }[] = [
    { value: 'text', label: t('create.typeOptions.text') },
    { value: 'integer', label: t('create.typeOptions.integer') },
    { value: 'float', label: t('create.typeOptions.float') },
    { value: 'date', label: t('create.typeOptions.date') },
    { value: 'boolean', label: t('create.typeOptions.boolean') },
  ];

  useEffect(() => {
    if (open) {
      setTitle('');
      setColumns([createEmptyColumn()]);
    }
  }, [open]);

  function addColumn() {
    setColumns((prev) => [...prev, createEmptyColumn()]);
  }

  function removeColumn(id: number) {
    setColumns((prev) => prev.filter((c) => c.id !== id));
  }

  function updateColumn(id: number, field: 'name' | 'type', value: string) {
    setColumns((prev) =>
      prev.map((c) => (c.id === id ? { ...c, [field]: value } : c)),
    );
  }

  function validate(): string | null {
    if (!title.trim()) return t('create.errors.titleRequired');
    if (columns.length === 0) return t('create.errors.columnRequired');
    const names = new Set<string>();
    for (const col of columns) {
      if (!col.name.trim()) return t('create.errors.columnNamesRequired');
      const lower = col.name.toLowerCase();
      if (names.has(lower)) return t('create.errors.duplicateColumn', { name: col.name });
      names.add(lower);
    }
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const error = validate();
    if (error) {
      toast.error(error);
      return;
    }

    createMutation.mutate(
      {
        title: title.trim(),
        columns: columns.map((c) => ({ name: c.name.trim(), type: c.type })),
      },
      {
        onSuccess: (dataset) => {
          toast.success(t('create.success'));
          onOpenChange(false);
          navigate(`/datasets/${dataset.id}`);
        },
        onError: (err) => {
          toast.error(err instanceof Error ? err.message : t('create.errors.createFailed'));
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('create.title')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="dataset-title">{t('create.datasetTitle')}</Label>
            <Input
              id="dataset-title"
              placeholder={t('create.datasetTitlePlaceholder')}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </div>

          <div className="space-y-2">
            <Label>{t('create.columns')}</Label>
            <div className="space-y-2">
              {columns.map((col) => (
                <div key={col.id} className="flex items-center gap-2">
                  <Input
                    placeholder={t('create.columnName')}
                    value={col.name}
                    onChange={(e) => updateColumn(col.id, 'name', e.target.value)}
                    className="flex-1"
                  />
                  <Select
                    value={col.type}
                    onValueChange={(v) => updateColumn(col.id, 'type', v)}
                  >
                    <SelectTrigger className="w-32">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {typeOptions.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => removeColumn(col.id)}
                    disabled={columns.length <= 1}
                    aria-label={t('create.removeColumn')}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
            <Button type="button" variant="outline" size="sm" onClick={addColumn}>
              <Plus className="h-4 w-4 me-1" />
              {t('create.addColumn')}
            </Button>
          </div>

          <div className="flex justify-end">
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending && <Loader2 className="size-4 animate-spin" />}
              {createMutation.isPending ? t('create.submitting') : t('create.submit')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
