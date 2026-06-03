/**
 * ISO 19115 constants shared across dataset detail components.
 */

export const UPDATE_FREQUENCY_OPTIONS = [
  'continual',
  'daily',
  'weekly',
  'fortnightly',
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
  'unclassified',
  'restricted',
  'confidential',
  'secret',
  'topSecret',
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
