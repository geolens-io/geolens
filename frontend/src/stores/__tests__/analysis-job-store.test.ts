import { beforeEach, describe, expect, it } from 'vitest';
import {
  useAnalysisJobStore,
  type TrackedAnalysisJob,
} from '@/stores/analysis-job-store';
import { useAuthStore } from '@/stores/auth-store';
import type { UserResponse } from '@/types/api';

// fix(#699): the tracked-job store had no tests at all, which left its three
// load-bearing behaviours unpinned — it persists (the whole point is
// outliving a closed panel or a reload), it rehydrates that persisted job on
// the next mount, and it drops the job when the signed-in identity changes so
// the next account on a shared browser does not inherit a run whose status
// endpoint will 403 forever.

const STORAGE_KEY = 'geolens-analysis-job';

const job: TrackedAnalysisJob = {
  jobId: 'job-1',
  title: 'Buffered parcels',
  mapId: 'map-1',
};

function persisted(): { job: TrackedAnalysisJob | null } | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  return raw ? JSON.parse(raw).state : null;
}

describe('analysis-job-store', () => {
  beforeEach(() => {
    useAnalysisJobStore.setState({ job: null });
    useAuthStore.setState({ token: null, refreshToken: null, user: null });
    localStorage.clear();
  });

  describe('persistence', () => {
    it('writes the tracked job to storage', () => {
      useAnalysisJobStore.getState().setJob(job);
      // toMatchObject, not toEqual: setJob also stamps the owning identity
      // (feat(#1008)), and these tests are about the job round-tripping, not
      // about who owns it — the ownership stamp has its own tests in
      // analysis-job-store.cross-tab.test.ts. Pinning the exact shape here
      // would make every future field addition fail three unrelated tests.
      expect(persisted()?.job).toMatchObject(job);
    });

    it('writes the cleared job through, rather than leaving a stale one behind', () => {
      useAnalysisJobStore.getState().setJob(job);
      useAnalysisJobStore.getState().setJob(null);
      expect(persisted()?.job).toBeNull();
    });

    it('rehydrates the job a previous session left behind', async () => {
      // Seeded last: any setState between here and rehydrate() would round-trip
      // the live (empty) state back out and overwrite the payload.
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ state: { job }, version: 1 }),
      );
      // A reload starts from the persisted payload; rehydrate() is the same
      // code path the middleware runs at store creation.
      await useAnalysisJobStore.persist.rehydrate();

      expect(useAnalysisJobStore.getState().job).toEqual(job);
    });

    it('ignores a payload written under an older version', async () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ state: { job }, version: 0 }),
      );
      await useAnalysisJobStore.persist.rehydrate();

      // No migrate function is declared, so a version mismatch discards the
      // payload rather than restoring a shape the current code cannot read.
      expect(useAnalysisJobStore.getState().job).toBeNull();
    });
  });

  describe('identity scoping', () => {
    it('clears the tracked job when another account signs in', () => {
      useAuthStore.setState({ user: { id: 'u1' } as UserResponse });
      useAnalysisJobStore.getState().setJob(job);

      useAuthStore.setState({ user: { id: 'u2' } as UserResponse });

      expect(useAnalysisJobStore.getState().job).toBeNull();
      expect(persisted()?.job).toBeNull();
    });

    it('clears the tracked job on logout', () => {
      useAuthStore.setState({ user: { id: 'u1' } as UserResponse, token: 't1' });
      useAnalysisJobStore.getState().setJob(job);

      useAuthStore.getState().logout();

      expect(useAnalysisJobStore.getState().job).toBeNull();
    });

    it('keeps the job through routine token rotation for the same user', () => {
      useAuthStore.setState({ user: { id: 'u1' } as UserResponse, token: 't1' });
      useAnalysisJobStore.getState().setJob(job);

      // A refresh rotates the token without changing who is signed in — the
      // guard keys on identity, not the token, so a long run survives it.
      useAuthStore.getState().setTokens('t2', 'r2', 900);

      expect(useAnalysisJobStore.getState().job).toMatchObject(job);
    });
  });
});
