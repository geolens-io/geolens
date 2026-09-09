import { describe, it, expect } from 'vitest';
import { INTERNAL_FAILURE_REASON, describeFailureReason } from '@/lib/failure-reason';

describe('describeFailureReason', () => {
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
});
