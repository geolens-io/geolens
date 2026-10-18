import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/stores/auth-store';
import { RoleCapabilityHint } from '@/components/dataset/RoleCapabilityHint';
import type { DatasetEditCapability } from '@/components/dataset/hooks/use-dataset-edit-capabilities';

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
  const signedIn = useAuthStore((state) => state.token != null);

  // An editable section already signals itself through its field shells, and signed-out
  // visitors can't be granted edit rights here, so the hint is only for signed-in read-only viewers.
  if (capability.editable || !signedIn) return null;

  return (
    <RoleCapabilityHint
      reason={capability.reason ?? 'read_only_field'}
      helper={t('affordances.sectionHint.readOnlyPassive')}
      className={className}
    />
  );
}
