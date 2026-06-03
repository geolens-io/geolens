export type DatasetTabValue =
  | 'overview'
  | 'metadata'
  | 'data'
  | 'structure';

export interface ValidationNavigationAction {
  anchor: string;
  defaultLabel: string;
  field: string;
  labelKey: string;
  priority: number;
  tab?: DatasetTabValue;
}

function normalizeField(field: string): string {
  return field.trim().toLowerCase().replace(/[-\s]+/g, '_');
}

export function getValidationNavigationAction(
  field: string,
): ValidationNavigationAction | null {
  const normalized = normalizeField(field);

  switch (normalized) {
    case 'summary':
      return {
        field,
        tab: 'overview',
        anchor: 'summary',
        labelKey: 'validation.actions.summary',
        defaultLabel: 'Review summary',
        priority: 10,
      };
    case 'contacts':
    case 'contact':
      return {
        field,
        tab: 'metadata',
        anchor: 'contacts',
        labelKey: 'validation.actions.contacts',
        defaultLabel: 'Review contacts',
        priority: 20,
      };
    case 'lineage_summary':
      return {
        field,
        tab: 'metadata',
        anchor: 'lineage_summary',
        labelKey: 'validation.actions.lineage',
        defaultLabel: 'Review lineage',
        priority: 30,
      };
    case 'source_url':
      return {
        field,
        tab: 'metadata',
        anchor: 'source_url',
        labelKey: 'validation.actions.sourceUrl',
        defaultLabel: 'Review source URL',
        priority: 40,
      };
    case 'source_organization':
      return {
        field,
        tab: 'metadata',
        anchor: 'source_organization',
        labelKey: 'validation.actions.sourceOrganization',
        defaultLabel: 'Review source organization',
        priority: 50,
      };
    case 'temporal_extent':
    case 'data_vintage_start':
    case 'data_vintage_end':
      return {
        field,
        tab: 'metadata',
        anchor: 'temporal_extent',
        labelKey: 'validation.actions.temporalExtent',
        defaultLabel: 'Review temporal extent',
        priority: 60,
      };
    case 'update_frequency':
      return {
        field,
        tab: 'metadata',
        anchor: 'update_frequency',
        labelKey: 'validation.actions.updateFrequency',
        defaultLabel: 'Review update cadence',
        priority: 70,
      };
    case 'quality_statement':
      return {
        field,
        tab: 'metadata',
        anchor: 'quality_statement',
        labelKey: 'validation.actions.qualityStatement',
        defaultLabel: 'Review quality statement',
        priority: 80,
      };
    case 'usage_constraints':
    case 'access_constraints':
    case 'sensitivity_classification':
      return {
        field,
        tab: 'metadata',
        anchor: 'governance',
        labelKey: 'validation.actions.governance',
        defaultLabel: 'Review governance',
        priority: 90,
      };
    case 'attribute_descriptions':
    case 'attribute_metadata':
      return {
        field,
        tab: 'structure',
        anchor: 'attribute_metadata',
        labelKey: 'validation.actions.attributeMetadata',
        defaultLabel: 'Review attributes',
        priority: 100,
      };
    case 'geometry':
    case 'geometry_validity':
    case 'geom':
    case 'crs':
    case 'srid':
    case 'extent':
    case 'bbox':
    case 'extent_bbox':
    case 'spatial_extent':
      return {
        field,
        anchor: 'dataset_map',
        labelKey: 'validation.actions.geometry',
        defaultLabel: 'Review geometry',
        priority: 110,
      };
    case 'validation':
      return {
        field,
        tab: 'metadata',
        anchor: 'validation',
        labelKey: 'validation.actions.validation',
        defaultLabel: 'Review validation',
        priority: 999,
      };
    default:
      return null;
  }
}
