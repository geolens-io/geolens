import { useTranslation } from 'react-i18next';
import { RoleCapabilityHint } from '@/components/dataset/RoleCapabilityHint';
import type { DatasetEditCapability } from '@/hooks/use-dataset-edit-capabilities';

interface SectionCapabilityHintProps {
  capability: DatasetEditCapability;
  className?: string;
}

/**
 * Thin wrapper around RoleCapabilityHint that resolves the editable/read-only
 * helper text for a dataset section based on the capability state.
 */
export function SectionCapabilityHint({ capability, className }: SectionCapabilityHintProps) {
  const { t } = useTranslation('dataset');

  const helper = capability.editable
    ? t('affordances.sectionHint.editable')
    : t('affordances.sectionHint.readOnlyPassive');

  return (
    <RoleCapabilityHint
      reason={capability.reason ?? 'read_only_field'}
      helper={helper}
      className={className}
    />
  );
}
