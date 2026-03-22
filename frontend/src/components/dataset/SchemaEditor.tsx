import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Trash2, Plus } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useAddColumn, useDropColumn } from '@/hooks/use-features';

const ALLOWED_TYPES = ['text', 'integer', 'real', 'boolean', 'date', 'timestamp'] as const;
const COLUMN_NAME_RE = /^[a-z][a-z0-9_]{0,62}$/;
const SYSTEM_COLUMNS = new Set(['gid', 'geom', 'geom_4326']);

interface SchemaEditorProps {
  datasetId: string;
  columns: { name: string; type: string }[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SchemaEditor({ datasetId, columns, open, onOpenChange }: SchemaEditorProps) {
  const { t } = useTranslation('dataset');
  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState<string>('text');
  const [nameError, setNameError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const addColumnMutation = useAddColumn();
  const dropColumnMutation = useDropColumn();

  const displayColumns = columns.filter((c) => !SYSTEM_COLUMNS.has(c.name));

  function validateName(name: string): string | null {
    if (!name) return t('schema.validation.required');
    if (!COLUMN_NAME_RE.test(name)) {
      return t('schema.validation.format');
    }
    if (SYSTEM_COLUMNS.has(name)) {
      return t('schema.validation.reserved');
    }
    if (columns.some((c) => c.name === name)) {
      return t('schema.validation.duplicate');
    }
    return null;
  }

  function handleAddColumn() {
    const error = validateName(newName);
    if (error) {
      setNameError(error);
      return;
    }

    addColumnMutation.mutate(
      { datasetId, column: { name: newName, type: newType } },
      {
        onSuccess: () => {
          toast.success(t('schema.columnAdded'));
          setNewName('');
          setNewType('text');
          setNameError(null);
        },
        onError: (err) => {
          toast.error(err instanceof Error ? err.message : t('schema.addFailed'));
        },
      },
    );
  }

  function handleDropColumn(columnName: string) {
    dropColumnMutation.mutate(
      { datasetId, columnName },
      {
        onSuccess: () => {
          toast.success(t('schema.columnRemoved'));
          setConfirmDelete(null);
        },
        onError: (err) => {
          toast.error(err instanceof Error ? err.message : t('schema.removeFailed'));
          setConfirmDelete(null);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('schema.title')}</DialogTitle>
          <DialogDescription>
            {t('schema.description')}
          </DialogDescription>
        </DialogHeader>

        {/* Existing columns */}
        {displayColumns.length > 0 ? (
          <div className="max-h-60 overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('schema.columnName')}</TableHead>
                  <TableHead>{t('schema.columnType')}</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {displayColumns.map((col) => (
                  <TableRow key={col.name}>
                    <TableCell className="font-mono text-xs">{col.name}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">{col.type}</TableCell>
                    <TableCell>
                      {confirmDelete === col.name ? (
                        <div className="flex items-center gap-1">
                          <Button
                            variant="destructive"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => handleDropColumn(col.name)}
                            disabled={dropColumnMutation.isPending}
                          >
                            {t('common:confirm')}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => setConfirmDelete(null)}
                          >
                            {t('common:cancel')}
                          </Button>
                        </div>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0"
                          onClick={() => setConfirmDelete(col.name)}
                          title={t('schema.removeColumn', { name: col.name })}
                        >
                          <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground py-4 text-center">
            {t('schema.noColumns')}
          </p>
        )}

        {/* Add column form */}
        <div className="border-t pt-4 space-y-3">
          <Label className="text-sm font-medium">{t('schema.addColumn')}</Label>
          <div className="flex items-start gap-2">
            <div className="flex-1 space-y-2">
              <Input
                placeholder={t('schema.columnNamePlaceholder')}
                value={newName}
                onChange={(e) => {
                  setNewName(e.target.value);
                  if (nameError) setNameError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleAddColumn();
                }}
                className="font-mono text-xs h-9"
              />
              {nameError && (
                <p className="text-xs text-destructive">{nameError}</p>
              )}
            </div>
            <Select value={newType} onValueChange={setNewType}>
              <SelectTrigger className="w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ALLOWED_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              size="sm"
              className="h-9"
              onClick={handleAddColumn}
              disabled={addColumnMutation.isPending || !newName}
            >
              <Plus className="h-4 w-4 mr-1" />
              {t('schema.add')}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
