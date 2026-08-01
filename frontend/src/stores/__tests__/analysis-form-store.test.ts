import { useAnalysisFormStore } from '@/stores/analysis-form-store';
import { useAuthStore } from '@/stores/auth-store';
import type { UserResponse } from '@/types/api';

const form = {
  layerId: 'l1',
  operation: 'buffer' as const,
  distance: '500',
  distanceUnit: 'm' as const,
  mask: null,
  maskLayerId: '__none__',
  byField: '__none__',
  joinLayerId: '__none__',
  joinField: '__none__',
  outputTitle: 'Walkshed',
};

describe('analysis-form-store auth scoping (#793 review)', () => {
  beforeEach(() => {
    useAnalysisFormStore.setState({ forms: {} });
    useAuthStore.setState({ token: null, refreshToken: null, user: null });
  });

  it('clears the saved form when the signed-in user changes', () => {
    useAuthStore.setState({ user: { id: 'u1' } as UserResponse });
    useAnalysisFormStore.getState().save('m1', form);
    // Logout, then another account signs in without a reload — the first
    // user's dataset name, parameters, and drawn mask must not restore.
    useAuthStore.getState().logout();
    expect(useAnalysisFormStore.getState().forms['m1']).toBeUndefined();
  });

  it('keeps independent snapshots per map (#793 review)', () => {
    useAnalysisFormStore.getState().save('m1', form);
    useAnalysisFormStore
      .getState()
      .save('m2', { ...form, outputTitle: 'Other map' });
    // Opening Analysis on map B must not cost map A its draft.
    expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe(
      'Walkshed',
    );
    expect(useAnalysisFormStore.getState().forms['m2']?.outputTitle).toBe(
      'Other map',
    );
  });

  it('survives routine token rotation for the same user', () => {
    useAuthStore.setState({ user: { id: 'u1' } as UserResponse, token: 't1' });
    useAnalysisFormStore.getState().save('m1', form);
    useAuthStore.getState().setTokens('t2', 'r2', 900);
    expect(useAnalysisFormStore.getState().forms['m1']?.outputTitle).toBe('Walkshed');
  });
});
