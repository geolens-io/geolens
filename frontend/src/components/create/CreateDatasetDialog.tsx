import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Loader2, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
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

type ColumnType = 'text' | 'integer' | 'float' | 'date' | 'boolean' | 'timestamp';

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
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);
  const focusColumnId = useRef<number | null>(null);

  const isDirty =
    title.trim() !== '' || columns.some((c) => c.name.trim() !== '' || c.type !== 'text');

  function requestClose() {
    // A failed create must leave the form in place to retry.
    if (createMutation.isPending) return;
    if (isDirty) {
      setDiscardConfirmOpen(true);
    } else {
      onOpenChange(false);
    }
  }

  const typeOptions: { value: ColumnType; label: string }[] = [
    { value: 'text', label: t('create.typeOptions.text') },
    { value: 'integer', label: t('create.typeOptions.integer') },
    { value: 'float', label: t('create.typeOptions.float') },
    { value: 'date', label: t('create.typeOptions.date') },
    { value: 'boolean', label: t('create.typeOptions.boolean') },
    { value: 'timestamp', label: t('create.typeOptions.timestamp') },
  ];

  useEffect(() => {
    if (open) {
      setTitle('');
      setColumns([createEmptyColumn()]);
    }
  }, [open]);

  function addColumn() {
    const column = createEmptyColumn();
    focusColumnId.current = column.id;
    setColumns((prev) => [...prev, column]);
  }

  useEffect(() => {
    if (focusColumnId.current === null) return;
    const input = document.getElementById(`column-name-${focusColumnId.current}`);
    focusColumnId.current = null;
    input?.scrollIntoView({ block: 'nearest' });
    input?.focus();
  }, [columns]);

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
    <>
      <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : requestClose())}>
        <DialogContent
          className="sm:max-w-lg max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)]"
          showCloseButton={!createMutation.isPending}>
          <DialogHeader>
            <DialogTitle>{t('create.title')}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="flex min-h-0 flex-col gap-4">
            <div
              data-testid="create-dataset-body"
              className="-mx-1 min-h-0 flex-1 space-y-4 overflow-y-auto px-1"
            >
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
                        id={`column-name-${col.id}`}
                        placeholder={t('create.columnName')}
                        value={col.name}
                        onChange={(e) => updateColumn(col.id, 'name', e.target.value)}
                        className="flex-1"
                      />
                      <Select
                        value={col.type}
                        onValueChange={(v) => updateColumn(col.id, 'type', v)}
                      >
                        <SelectTrigger className="w-32" aria-label={t('create.columnType')}>
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
            </div>

            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={requestClose}
                disabled={createMutation.isPending}
              >
                {t('common:cancel')}
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending && <Loader2 className="size-4 animate-spin" />}
                {createMutation.isPending ? t('create.submitting') : t('create.submit')}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <AlertDialog open={discardConfirmOpen} onOpenChange={setDiscardConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('create.discardTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('create.discardDescription')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('create.keepEditing')}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                setDiscardConfirmOpen(false);
                onOpenChange(false);
              }}
            >
              {t('create.discardAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
