// fix(#1778): Terra Draw undo history grew without bound and was never reset
// on the feature-edit (drag) path. These tests mock the `terra-draw` and
// `terra-draw-maplibre-gl-adapter` packages so the hook's `change`/`finish`
// handlers can be driven directly, without a real WebGL map.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useTerraDraw } from '@/components/drawing/hooks/use-terra-draw';

type Listener = (...args: unknown[]) => void;

class FakeTerraDraw {
  listeners: Record<string, Listener[]> = {};
  enabled = true;
  on(event: string, cb: Listener) {
    (this.listeners[event] ??= []).push(cb);
  }
  off(event: string, cb: Listener) {
    this.listeners[event] = (this.listeners[event] ?? []).filter((c) => c !== cb);
  }
  emit(event: string, ...args: unknown[]) {
    for (const cb of [...(this.listeners[event] ?? [])]) cb(...args);
  }
  start = vi.fn();
  stop = vi.fn();
  getSnapshot = vi.fn(() => [{ properties: { mode: 'point' } }] as unknown[]);
  getSnapshotFeature = vi.fn((id: string | number) => ({
    type: 'Feature',
    id,
    properties: { mode: 'point' },
    geometry: { type: 'Point', coordinates: [0, 0] },
  }));
  removeFeatures = vi.fn();
  addFeatures = vi.fn();
  clear = vi.fn();
  selectFeature = vi.fn();
  setMode = vi.fn();
}

let lastInstance: FakeTerraDraw | null = null;

vi.mock('terra-draw', () => ({
  TerraDraw: vi.fn().mockImplementation(function TerraDrawCtor() {
    lastInstance = new FakeTerraDraw();
    return lastInstance;
  }),
  TerraDrawPointMode: vi.fn(),
  TerraDrawLineStringMode: vi.fn(),
  TerraDrawPolygonMode: vi.fn(),
  TerraDrawRectangleMode: vi.fn(),
  TerraDrawCircleMode: vi.fn(),
  TerraDrawFreehandMode: vi.fn(),
  TerraDrawSelectMode: vi.fn(),
}));

vi.mock('terra-draw-maplibre-gl-adapter', () => ({
  TerraDrawMapLibreGLAdapter: vi.fn(),
}));

function fakeMap(): MaplibreMap {
  return {
    getStyle: () => ({ layers: [], sources: {} }),
    removeLayer: vi.fn(),
    removeSource: vi.fn(),
  } as unknown as MaplibreMap;
}

afterEach(() => {
  lastInstance = null;
});

describe('useTerraDraw — undo history bound (fix #1778)', () => {
  it('caps history growth instead of retaining one snapshot per change event forever', () => {
    const map = fakeMap();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), null));
    const td = lastInstance!;

    // Simulate a long drag/freehand trace: far more `change` events than the
    // 50-entry cap, with no 'finish' in between (mirrors the reported class:
    // one full store snapshot pushed per mousemove-derived update).
    act(() => {
      for (let i = 0; i < 200; i++) td.emit('change');
    });

    // Count how many undo steps are actually available. An unbounded ring
    // would allow 199 undos (200 pushes); a ring capped at 50 allows at
    // most 49.
    let undoCount = 0;
    while (result.current.canUndo && undoCount < 500) {
      act(() => {
        result.current.undo();
      });
      undoCount++;
    }
    expect(undoCount).toBeLessThanOrEqual(49);
    expect(undoCount).toBeGreaterThan(0);
  });

  // fix(round1 #1795, P2): a drag/vertex edit only marks the edit dirty
  // (use-feature-editing's handleEditFinish) — it is not persisted until
  // Save, so Undo must still be able to revert it. Resetting history right
  // on 'finish' disabled Undo for a pending, unsaved edit.
  it('keeps undo history available after a committed feature edit (dragFeature) finishes — Undo still reverts it', () => {
    const map = fakeMap();
    const onEditFinish = vi.fn();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), onEditFinish));
    const td = lastInstance!;

    // Push enough 'change' snapshots (as if dragging a feature) to make undo available.
    act(() => {
      td.emit('change');
      td.emit('change');
    });
    expect(result.current.canUndo).toBe(true);

    // Commit the drag — this is the 'finish' event with a drag action.
    act(() => {
      td.emit('finish', 'feat-1', { action: 'dragFeature', mode: 'select' });
    });

    expect(onEditFinish).toHaveBeenCalledWith('feat-1', expect.anything());
    // Undo is still enabled and can revert the just-finished drag.
    expect(result.current.canUndo).toBe(true);
    act(() => {
      result.current.undo();
    });
    expect(td.clear).toHaveBeenCalled();
    expect(td.addFeatures).toHaveBeenCalled();
  });

  // fix(round1 #1795, P2): the pending edit's history is discarded once it
  // actually settles — save, cancel, or deselection — via the exposed
  // resetHistory(), not by the hook itself reacting to 'finish'.
  it('resetHistory() disables Undo once the caller settles the pending edit (e.g. after Save)', () => {
    const map = fakeMap();
    const onEditFinish = vi.fn();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), onEditFinish));
    const td = lastInstance!;

    act(() => {
      td.emit('change');
      td.emit('change');
      td.emit('finish', 'feat-1', { action: 'dragFeature', mode: 'select' });
    });
    expect(result.current.canUndo).toBe(true);

    act(() => {
      result.current.resetHistory();
    });
    expect(result.current.canUndo).toBe(false);
  });
});

// fix(round2 #1795, P2): undo() reverts snapshots and updates canUndo, but
// never touched isEditDirty — undoing all the way back to the original
// geometry still triggered the unsaved-changes confirmation on Cancel/Done/
// mode-switch. onHistoryBaseline is the signal the editing layer uses to
// clear isEditDirty at exactly the right moment.
describe('useTerraDraw — onHistoryBaseline (fix round2/round3 #1795)', () => {
  // fix(round3 #1795): with a captured baseline, reaching the ring's own
  // oldest entry (round2's old "atBaseline" condition) is NOT the true
  // pre-edit snapshot — it's just as far as the RING goes. One more undo
  // step, falling back to baselineRef, is what actually restores the
  // original geometry and fires the callback.
  it('fires onHistoryBaseline only on the undo() call that reaches the TRUE captured baseline, not when the ring itself is merely exhausted', () => {
    const map = fakeMap();
    const onHistoryBaseline = vi.fn();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), null, onHistoryBaseline));
    const td = lastInstance!;

    // Selecting a feature captures the TRUE pre-edit baseline outside the ring.
    act(() => {
      result.current.selectFeature('feat-1');
    });

    // Three snapshots recorded (ring length 3).
    act(() => {
      td.emit('change');
      td.emit('change');
      td.emit('change');
    });
    expect(result.current.canUndo).toBe(true);

    // First undo: ring still has more than one entry left.
    act(() => {
      result.current.undo();
    });
    expect(onHistoryBaseline).not.toHaveBeenCalled();
    expect(result.current.canUndo).toBe(true);

    // Second undo: only the ring's own oldest entry remains. NOT the true
    // baseline yet — canUndo stays true only because a baseline was captured.
    act(() => {
      result.current.undo();
    });
    expect(onHistoryBaseline).not.toHaveBeenCalled();
    expect(result.current.canUndo).toBe(true);

    // Third undo: the ring is now empty — the TRUE baseline is restored.
    act(() => {
      result.current.undo();
    });
    expect(onHistoryBaseline).toHaveBeenCalledTimes(1);
    expect(result.current.canUndo).toBe(false);
  });

  it('does NOT fire onHistoryBaseline from resetHistory(), clear(), or setMode() — only from undo()', () => {
    const map = fakeMap();
    const onHistoryBaseline = vi.fn();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), null, onHistoryBaseline));
    const td = lastInstance!;

    act(() => {
      td.emit('change');
      td.emit('change');
    });
    expect(result.current.canUndo).toBe(true);

    act(() => {
      result.current.resetHistory();
    });
    expect(onHistoryBaseline).not.toHaveBeenCalled();

    act(() => {
      td.emit('change');
      td.emit('change');
    });
    act(() => {
      result.current.clear();
    });
    expect(onHistoryBaseline).not.toHaveBeenCalled();

    act(() => {
      td.emit('change');
      td.emit('change');
    });
    act(() => {
      result.current.setMode('point');
    });
    expect(onHistoryBaseline).not.toHaveBeenCalled();
  });

  it('an undo() call after the ring is already exhausted with no baseline (no-op) does not fire onHistoryBaseline', () => {
    const map = fakeMap();
    const onHistoryBaseline = vi.fn();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), null, onHistoryBaseline));
    const td = lastInstance!;

    // No selectFeature()/setMode() call — no baseline captured.
    act(() => {
      td.emit('change');
    });
    // fix(round3 #1795): with no captured baseline, one ring entry is as far
    // as undo can verifiably go — canUndo is false, same as before this fix.
    expect(result.current.canUndo).toBe(false);

    act(() => {
      result.current.undo(); // guarded no-op: canUndoFrom(1, false) === false
    });
    expect(onHistoryBaseline).not.toHaveBeenCalled();
  });

  // fix(round3 #1795, P2 pin): after more than MAX_UNDO_HISTORY (50) change
  // events in one drag, the ring's shift() evicts the original pre-edit
  // snapshot. Undo must still reach the TRUE original geometry — not
  // whatever the ring's own (now-not-original) oldest surviving entry is —
  // and onHistoryBaseline must fire exactly once, on that final step.
  it('undoing past an evicted ring restores the TRUE pre-edit baseline, not a stale ring entry (60 changes, cap 50)', () => {
    const map = fakeMap();
    const onHistoryBaseline = vi.fn();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), null, onHistoryBaseline));
    const td = lastInstance!;

    const baselineSnapshot = [{ properties: { mode: 'point', tag: 'baseline' } }] as unknown[];
    td.getSnapshot.mockReturnValue(baselineSnapshot);
    act(() => {
      result.current.selectFeature('feat-1');
    });

    // 60 change events — the ring (cap 50) evicts its oldest 10 entries, so
    // its surviving oldest entry ("change-11") is NOT the true baseline.
    for (let i = 1; i <= 60; i++) {
      td.getSnapshot.mockReturnValue([{ properties: { mode: 'point', tag: `change-${i}` } }] as unknown[]);
      act(() => {
        td.emit('change');
      });
    }
    expect(result.current.canUndo).toBe(true);

    let undoCount = 0;
    while (result.current.canUndo && undoCount < 200) {
      act(() => {
        result.current.undo();
      });
      undoCount++;
    }

    // 50 ring entries take exactly 50 undo() calls to exhaust: 49 step
    // through the ring, the 50th falls back to the true baseline.
    expect(undoCount).toBe(50);
    expect(onHistoryBaseline).toHaveBeenCalledTimes(1);
    const lastAddFeaturesCall = td.addFeatures.mock.calls[td.addFeatures.mock.calls.length - 1];
    expect(lastAddFeaturesCall[0]).toEqual(baselineSnapshot);
  });

  // fix(round3 #1795, P2 pin): if the session's baseline was never captured
  // (e.g. change events reached the hook before any recognized
  // session-start point ran), undo must refuse to fabricate one — the ring
  // stops at its own oldest entry and onHistoryBaseline never fires, so
  // isEditDirty stays true.
  it('with the baseline deliberately missing, onHistoryBaseline never fires even after undo is fully exhausted', () => {
    const map = fakeMap();
    const onHistoryBaseline = vi.fn();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), null, onHistoryBaseline));
    const td = lastInstance!;

    // No selectFeature()/setMode() call anywhere in this test.
    act(() => {
      td.emit('change');
      td.emit('change');
      td.emit('change');
    });
    expect(result.current.canUndo).toBe(true);

    let undoCount = 0;
    while (result.current.canUndo && undoCount < 200) {
      act(() => {
        result.current.undo();
      });
      undoCount++;
    }

    // Refused to go past the ring's own oldest entry without a verified baseline.
    expect(undoCount).toBe(2);
    expect(onHistoryBaseline).not.toHaveBeenCalled();
    expect(result.current.canUndo).toBe(false);
  });
});

// fix(round4 #1795, P2): undo()'s restoring draw.clear() drops Terra Draw's
// own select-mode state and edit handles. Without re-selecting afterward,
// the app's selection store still shows the feature selected, but Terra
// Draw does not — the user has to click the geometry again before dragging
// or editing vertices.
describe('useTerraDraw — undo() re-selects the previously selected feature (fix round4 #1795)', () => {
  it('re-selects after restoring an intermediate ring snapshot, in the correct order (clear, addFeatures, THEN selectFeature)', () => {
    const map = fakeMap();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), null));
    const td = lastInstance!;

    const callLog: string[] = [];
    td.clear.mockImplementation(() => { callLog.push('clear'); });
    td.addFeatures.mockImplementation((f: unknown) => { callLog.push(`addFeatures:${JSON.stringify(f)}`); });
    td.selectFeature.mockImplementation((id: string | number) => { callLog.push(`selectFeature:${id}`); });

    const withFeature = (tag: string) => [{ id: 'feat-1', properties: { mode: 'point', tag } }] as unknown[];

    td.getSnapshot.mockReturnValue(withFeature('baseline'));
    act(() => {
      result.current.selectFeature('feat-1');
    });
    expect(td.selectFeature).toHaveBeenCalledWith('feat-1');
    callLog.length = 0;

    td.getSnapshot.mockReturnValue(withFeature('change-1'));
    act(() => { td.emit('change'); });
    td.getSnapshot.mockReturnValue(withFeature('change-2'));
    act(() => { td.emit('change'); });

    act(() => {
      result.current.undo();
    });

    expect(td.addFeatures).toHaveBeenCalledWith(withFeature('change-1'));
    expect(td.selectFeature).toHaveBeenCalledWith('feat-1');
    // Terra Draw's own select state/edit handles only exist AFTER the
    // feature is back on the canvas — selectFeature must run after
    // addFeatures, both of which run after clear().
    expect(callLog).toEqual([
      'clear',
      `addFeatures:${JSON.stringify(withFeature('change-1'))}`,
      'selectFeature:feat-1',
    ]);
  });

  // fix(round4 #1795): the round3 baseline-fallback undo (ring exhausted,
  // restoring baselineRef) shares the SAME restoration code path as a
  // ring-internal undo — this pins that the re-select fix covers it too.
  it('re-selects after falling back to the true baseline (round3 baseline-fallback path)', () => {
    const map = fakeMap();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), null));
    const td = lastInstance!;

    const withFeature = (tag: string) => [{ id: 'feat-1', properties: { mode: 'point', tag } }] as unknown[];

    td.getSnapshot.mockReturnValue(withFeature('baseline'));
    act(() => {
      result.current.selectFeature('feat-1');
    });
    (td.selectFeature as ReturnType<typeof vi.fn>).mockClear();

    td.getSnapshot.mockReturnValue(withFeature('change-1'));
    act(() => { td.emit('change'); });

    // One change only — ring length 1. This undo pops the ring to empty and
    // falls back to the TRUE baseline (fix round3 #1795), not a ring entry.
    act(() => {
      result.current.undo();
    });

    expect(td.addFeatures).toHaveBeenCalledWith(withFeature('baseline'));
    expect(td.selectFeature).toHaveBeenCalledWith('feat-1');
    expect(result.current.canUndo).toBe(false);
  });

  it('clears the selection record and reports onSelectionLost when the restored snapshot no longer has that feature', () => {
    const map = fakeMap();
    const onSelectionLost = vi.fn();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), null, undefined, onSelectionLost));
    const td = lastInstance!;

    td.getSnapshot.mockReturnValue([{ id: 'feat-1', properties: { mode: 'point', tag: 'baseline' } }] as unknown[]);
    act(() => {
      result.current.selectFeature('feat-1');
    });
    (td.selectFeature as ReturnType<typeof vi.fn>).mockClear();

    // The restored ring entries never contain feat-1 (only a different feature).
    td.getSnapshot.mockReturnValue([{ id: 'other-feat', properties: { mode: 'point', tag: 'change-1' } }] as unknown[]);
    act(() => { td.emit('change'); });
    td.getSnapshot.mockReturnValue([{ id: 'other-feat', properties: { mode: 'point', tag: 'change-2' } }] as unknown[]);
    act(() => { td.emit('change'); });

    act(() => {
      result.current.undo();
    });

    expect(td.selectFeature).not.toHaveBeenCalled();
    expect(onSelectionLost).toHaveBeenCalledTimes(1);
    expect(onSelectionLost).toHaveBeenCalledWith('feat-1');

    // A second undo (falling back to the true baseline, which DOES have
    // feat-1) must not still think feat-1 is selected from a stale record —
    // it was cleared, so onSelectionLost is not reported a second time and
    // selectFeature is not spuriously called either.
    act(() => {
      result.current.undo();
    });
    expect(td.selectFeature).not.toHaveBeenCalled();
    expect(onSelectionLost).toHaveBeenCalledTimes(1);
  });
});

// fix(round5 #1795, P2): on the real selection path, addFeatures() and
// draw.selectFeature() synchronously emit `change` events — without a
// guard, the ring already holds those seed snapshots by the time
// selectFeature() captures the session's baseline, so canUndo/isEditDirty
// read as "dirty" right after just selecting a feature, before any actual
// edit happened.
describe('useTerraDraw — selecting a feature does not seed the undo ring (fix round5 #1795)', () => {
  it('selecting a feature (which synchronously emits change, like the real selection path) leaves canUndo false and the ring empty', () => {
    const map = fakeMap();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), null));
    const td = lastInstance!;

    // Simulate the real selection path: draw.selectFeature() synchronously
    // fires a `change` event, same as terra-draw's actual select mode does.
    td.getSnapshot.mockReturnValue([{ id: 'feat-1', properties: { mode: 'point', tag: 'seed' } }] as unknown[]);
    td.selectFeature.mockImplementation(() => { td.emit('change'); });

    act(() => {
      result.current.selectFeature('feat-1');
    });

    expect(result.current.canUndo).toBe(false);
    // The ring is truly empty, not "1 seed entry" masquerading as a real
    // edit — a further undo() has nothing to restore.
    act(() => {
      result.current.undo();
    });
    expect(td.addFeatures).not.toHaveBeenCalled();
  });

  it('one drag after selection, then one undo: canUndo goes false and the drag is fully reverted to the true baseline', () => {
    const map = fakeMap();
    const onHistoryBaseline = vi.fn();
    const { result } = renderHook(() => useTerraDraw(map, vi.fn(), null, onHistoryBaseline));
    const td = lastInstance!;

    const baselineSnapshot = [{ id: 'feat-1', properties: { mode: 'point', tag: 'baseline' } }] as unknown[];
    td.getSnapshot.mockReturnValue(baselineSnapshot);
    // Selection itself synchronously seeds a `change` event.
    td.selectFeature.mockImplementation(() => { td.emit('change'); });
    act(() => {
      result.current.selectFeature('feat-1');
    });
    expect(result.current.canUndo).toBe(false);

    // One drag.
    td.selectFeature.mockImplementation(() => {});
    td.getSnapshot.mockReturnValue([{ id: 'feat-1', properties: { mode: 'point', tag: 'dragged' } }] as unknown[]);
    act(() => { td.emit('change'); });
    expect(result.current.canUndo).toBe(true);

    act(() => {
      result.current.undo();
    });

    expect(result.current.canUndo).toBe(false);
    expect(onHistoryBaseline).toHaveBeenCalledTimes(1);
    expect(td.addFeatures).toHaveBeenCalledWith(baselineSnapshot);
  });
});
