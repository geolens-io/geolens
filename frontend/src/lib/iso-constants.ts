/**
 * ISO 19115 constants shared across dataset detail components.
 *
 * Both option lists below must stay a subset of the records CHECK constraints
 * they feed (chk_records_update_frequency / chk_records_sensitivity in
 * backend/app/modules/catalog/datasets/domain/models.py) -- an option the
 * constraint rejects 500s the whole pending-edit batch on save. See
 * backend/tests/test_iso_option_drift.py.
 */

export const UPDATE_FREQUENCY_OPTIONS = [
  'continual',
  'daily',
  'weekly',
  'monthly',
  'quarterly',
  'biannually',
  'annually',
  'asNeeded',
  'irregular',
  'notPlanned',
  'unknown',
] as const;

export const SENSITIVITY_OPTIONS = [
  'public',
  'internal',
  'confidential',
  'restricted',
] as const;

export const THEME_CATEGORIES = [
  'farming',
  'biota',
  'boundaries',
  'climatologyMeteorologyAtmosphere',
  'economy',
  'elevation',
  'environment',
  'geoscientificInformation',
  'health',
  'imageryBaseMapsEarthCover',
  'intelligenceMilitary',
  'inlandWaters',
  'location',
  'oceans',
  'planningCadastre',
  'society',
  'structure',
  'transportation',
  'utilitiesCommunication',
] as const;
