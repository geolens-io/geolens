import { useMemo } from 'react';
import { useAuthStore } from '@/stores/auth-store';

export type DatasetEditField =
  | 'title'
  | 'summary'
  | 'source_url'
  | 'source_organization'
  | 'lineage_summary'
  | 'update_frequency'
  | 'usage_constraints'
  | 'access_constraints'
  | 'sensitivity_classification'
  | 'quality_statement'
  | 'data_vintage_start'
  | 'data_vintage_end'
  | 'theme_category'
  | 'record_status'
  | 'feature_count'
  | 'geometry_type'
  | 'table_name'
  | 'source_format'
  | 'created_at'
  | 'updated_at';

export type DatasetCapabilityReason = 'insufficient_role' | 'read_only_field';

export interface DatasetEditCapability {
  editable: boolean;
  canAttempt: boolean;
  reason: DatasetCapabilityReason | null;
  helper?: string;
}

export type DatasetEditCapabilities = Record<DatasetEditField, DatasetEditCapability>;

interface BuildDatasetEditCapabilitiesInput {
  isEditor: boolean;
  helperOverrides?: Partial<Record<DatasetEditField, string>>;
}

const EDITABLE_FIELDS: DatasetEditField[] = [
  'title',
  'summary',
  'source_url',
  'source_organization',
  'lineage_summary',
  'update_frequency',
  'usage_constraints',
  'access_constraints',
  'sensitivity_classification',
  'quality_statement',
  'data_vintage_start',
  'data_vintage_end',
  'theme_category',
];

const READ_ONLY_FIELDS: DatasetEditField[] = [
  'record_status',
  'feature_count',
  'geometry_type',
  'table_name',
  'source_format',
  'created_at',
  'updated_at',
];

const VIEWER_HELPER = 'You can view this field. Editors can make changes.';
const READ_ONLY_HELPER = 'This field is read-only.';
const EDITOR_HELPER = 'Click to edit this field.';

export function buildDatasetEditCapabilities({
  isEditor,
  helperOverrides,
}: BuildDatasetEditCapabilitiesInput): DatasetEditCapabilities {
  const editableSet = new Set(EDITABLE_FIELDS);

  const allFields = [...EDITABLE_FIELDS, ...READ_ONLY_FIELDS] as DatasetEditField[];

  return allFields.reduce<DatasetEditCapabilities>((capabilities, field) => {
    const isEditableField = editableSet.has(field);
    const isFieldViewerDenied = isEditableField && !isEditor;
    const isFieldEditable = isEditableField && isEditor;

    capabilities[field] = {
      editable: isFieldEditable,
      canAttempt: isFieldEditable || isFieldViewerDenied,
      reason: isFieldEditable
        ? null
        : (isFieldViewerDenied ? 'insufficient_role' : 'read_only_field'),
      helper: helperOverrides?.[field] ?? (
        isFieldEditable
          ? EDITOR_HELPER
          : (isFieldViewerDenied ? VIEWER_HELPER : READ_ONLY_HELPER)
      ),
    };
    return capabilities;
  }, {} as DatasetEditCapabilities);
}

export function useDatasetEditCapabilities(
  helperOverrides?: Partial<Record<DatasetEditField, string>>,
) {
  const isEditor = useAuthStore((state) => state.isEditor());

  return useMemo(
    () => buildDatasetEditCapabilities({
      isEditor,
      helperOverrides,
    }),
    [helperOverrides, isEditor],
  );
}
