import { useState, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { useAttributes, useUpdateAttribute } from '@/hooks/use-dataset';
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Loader2 } from 'lucide-react';
import type { AttributeMetadataResponse, AttributeMetadataUpdate } from '@/types/api';

interface AttributeMetadataTableProps {
  datasetId: string;
  canEdit: boolean;
}

type EditableField = 'title' | 'description' | 'units';

interface EditingCell {
  attributeId: string;
  field: EditableField;
}

function sortByOrdinal(a: AttributeMetadataResponse, b: AttributeMetadataResponse): number {
  const aPos = a.ordinal_position ?? Number.MAX_SAFE_INTEGER;
  const bPos = b.ordinal_position ?? Number.MAX_SAFE_INTEGER;
  return aPos - bPos;
}

export function AttributeMetadataTable({ datasetId, canEdit }: AttributeMetadataTableProps) {
  const { t } = useTranslation('dataset');
  const { data, isLoading } = useAttributes(datasetId);
  const updateAttribute = useUpdateAttribute(datasetId);
  const [editingCell, setEditingCell] = useState<EditingCell | null>(null);
  const [editValue, setEditValue] = useState('');
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, [editingCell]);

  const startEditing = useCallback(
    (attr: AttributeMetadataResponse, field: EditableField) => {
      if (!canEdit) return;
      setEditingCell({ attributeId: attr.id, field });
      setEditValue(attr[field] ?? '');
    },
    [canEdit],
  );

  const saveEdit = useCallback(async () => {
    if (!editingCell) return;
    const trimmed = editValue.trim();
    const payload: AttributeMetadataUpdate = {
      [editingCell.field]: trimmed || null,
    };
    try {
      await updateAttribute.mutateAsync({
        attributeId: editingCell.attributeId,
        data: payload,
      });
      toast.success(t('attributeMetadata.updated'));
    } catch {
      toast.error(t('attributeMetadata.updateFailed'));
    }
    setEditingCell(null);
  }, [editingCell, editValue, updateAttribute, t]);

  const cancelEdit = useCallback(() => {
    setEditingCell(null);
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        saveEdit();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        cancelEdit();
      }
    },
    [saveEdit, cancelEdit],
  );

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  const currentAttributes = (data?.attributes ?? [])
    .filter((a) => a.is_current)
    .sort(sortByOrdinal);

  if (currentAttributes.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4 text-center">
        {t('attributeMetadata.noAttributes')}
      </p>
    );
  }

  function renderCell(attr: AttributeMetadataResponse, field: EditableField) {
    const isEditing =
      editingCell?.attributeId === attr.id && editingCell?.field === field;

    if (isEditing) {
      return (
        <Input
          ref={inputRef}
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={saveEdit}
          onKeyDown={handleKeyDown}
          className="h-7 text-xs"
        />
      );
    }

    const value = attr[field];
    if (canEdit) {
      return (
        <button
          type="button"
          onClick={() => startEditing(attr, field)}
          className="w-full text-left rounded px-1 -mx-1 hover:bg-accent/50 transition-colors text-xs min-h-[1.75rem] flex items-center"
          title={t('attributeMetadata.clickToEdit')}
        >
          {value || (
            <span className="text-muted-foreground italic">
              {t('attributeMetadata.clickToEdit')}
            </span>
          )}
        </button>
      );
    }

    return <span className="text-xs">{value || '-'}</span>;
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader className="sticky top-0 bg-muted/80 backdrop-blur-sm">
          <TableRow>
            <TableHead className="w-[140px]">{t('attributeMetadata.fieldName')}</TableHead>
            <TableHead>{t('attributeMetadata.attrTitle')}</TableHead>
            <TableHead>{t('attributeMetadata.description')}</TableHead>
            <TableHead className="w-[100px]">{t('attributeMetadata.type')}</TableHead>
            <TableHead className="w-[100px]">{t('attributeMetadata.units')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {updateAttribute.isPending && (
            <TableRow>
              <TableCell colSpan={5} className="h-0 p-0 border-0">
                <div className="flex justify-center">
                  <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                </div>
              </TableCell>
            </TableRow>
          )}
          {currentAttributes.map((attr) => (
            <TableRow key={attr.id}>
              <TableCell className="font-mono text-xs">
                <div className="flex items-center gap-1.5">
                  {attr.field_name}
                  {attr.semantic_role && (
                    <Badge variant="outline" className="text-[10px] px-1 py-0">
                      {attr.semantic_role}
                    </Badge>
                  )}
                </div>
              </TableCell>
              <TableCell>{renderCell(attr, 'title')}</TableCell>
              <TableCell>{renderCell(attr, 'description')}</TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {attr.data_type ?? '-'}
              </TableCell>
              <TableCell>{renderCell(attr, 'units')}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
