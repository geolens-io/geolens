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
  const signedIn = Boolean(useAuthStore((state) => state.token));

  // When the section is editable, the inline pencil + editable field shells already
  // signal it; the extra third-person "Editors can update fields…" banner is noise,
  // so only surface the hint for the read-only case.
  // Signed-out visitors can't be granted edit rights by this page, so the hint is noise for them.
  if (capability.editable || !signedIn) return null;

  return (
    <RoleCapabilityHint
      reason={capability.reason ?? 'read_only_field'}
      helper={t('affordances.sectionHint.readOnlyPassive')}
      className={className}
    />
  );
}
