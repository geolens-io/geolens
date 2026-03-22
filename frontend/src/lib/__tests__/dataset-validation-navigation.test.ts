import { getValidationNavigationAction } from '@/lib/dataset-validation-navigation';

describe('dataset validation navigation', () => {
  it('routes metadata issues to the metadata tab', () => {
    expect(getValidationNavigationAction('contacts')).toMatchObject({
      tab: 'metadata',
      anchor: 'contacts',
    });

    expect(getValidationNavigationAction('lineage_summary')).toMatchObject({
      tab: 'metadata',
      anchor: 'lineage_summary',
    });

    expect(getValidationNavigationAction('validation')).toMatchObject({
      tab: 'metadata',
      anchor: 'validation',
    });
  });

  it('keeps overview and structure mappings for summary and attribute metadata', () => {
    expect(getValidationNavigationAction('summary')).toMatchObject({
      tab: 'overview',
      anchor: 'summary',
    });

    expect(getValidationNavigationAction('attribute_descriptions')).toMatchObject({
      tab: 'structure',
      anchor: 'attribute_metadata',
    });
  });
});
