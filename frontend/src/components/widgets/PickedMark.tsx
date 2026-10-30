import { useTranslation } from 'react-i18next';

/** The mark on a picked bar, bin or table row; never the only cue, since picks also change weight or fade the rest. */
export const PICKED_GLYPH = '✓';

export function PickedMark() {
  const { t } = useTranslation('widgets');
  return (
    <>
      <span aria-hidden="true" className="ms-1 font-semibold">
        {PICKED_GLYPH}
      </span>
      <span className="sr-only"> ({t('picked')})</span>
    </>
  );
}
