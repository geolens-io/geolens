import { afterEach, describe, it, expect } from 'vitest';
import {
  INTERNAL_FAILURE_REASON,
  describeFailureReason,
  fixedFailureReason,
} from '@/lib/failure-reason';
import { changeTestLanguage } from '@/test/i18n';

describe('describeFailureReason', () => {
  afterEach(async () => {
    await changeTestLanguage('en');
  });

  it('replaces the coded reason with the localized line', () => {
    expect(describeFailureReason(INTERNAL_FAILURE_REASON, 'Something went wrong')).toBe(
      'Something went wrong',
    );
  });

  it('leaves a message the server composed alone', () => {
    const composed = "Layer 'parcels' has no geometry column";
    expect(describeFailureReason(composed, 'Something went wrong')).toBe(composed);
  });

  it('pins the code the backend stores', () => {
    // Mirrors INTERNAL_FAILURE_REASON in backend/app/core/failure_reason.py.
    expect(INTERNAL_FAILURE_REASON).toBe('internal_error');
  });

  it("shows a fixed reason in the reader's language", async () => {
    await changeTestLanguage('de');

    expect(describeFailureReason('Cancelled by user', 'Something went wrong', 'user_cancelled')).toBe(
      'Vom Benutzer abgebrochen',
    );
  });

  it('keeps the stored reason for a code with no fixed sentence', () => {
    const composed = 'Rejected before execution: source_changed.';
    expect(describeFailureReason(composed, 'Something went wrong', 'source_changed')).toBe(composed);
    expect(fixedFailureReason(null)).toBeUndefined();
  });
});
