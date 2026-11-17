import type { Hierarchy } from 'copc';
import {
  CHEAP_RANGE_BYTES,
  MAX_LARGE_NODES,
  MAX_NODE_DECODED_BYTES,
  MAX_RANGE_BYTES,
  MAX_SELECTED_BYTES,
  MAX_SELECTED_NODES,
  POINT_BUDGET,
} from './copc-limits';

const NODE_KEY = /^(\d{1,2})-(-?\d{1,9})-(-?\d{1,9})-(-?\d{1,9})$/;

/** The depth of a node the viewer can read, or null for an entry that is dropped. */
function usableDepth(
  key: string,
  node: Hierarchy.Node | undefined,
  recordLength: number,
  fileSize: number | null,
): number | null {
  const depth = NODE_KEY.exec(key)?.[1];
  if (!node || depth === undefined) return null;
  const { pointCount, pointDataOffset, pointDataLength } = node;
  if (!Number.isSafeInteger(pointCount) || pointCount <= 0 || pointCount > POINT_BUDGET) return null;
  if (pointCount * recordLength > MAX_NODE_DECODED_BYTES) return null;
  if (!Number.isSafeInteger(pointDataOffset) || pointDataOffset < 0) return null;
  if (!Number.isSafeInteger(pointDataLength) || pointDataLength <= 0 || pointDataLength > MAX_RANGE_BYTES) return null;
  if (fileSize !== null && pointDataOffset + pointDataLength > fileSize) return null;
  return Number(depth);
}

interface Picked {
  selected: [string, Hierarchy.Node][];
  /** A budget ended the selection, so no deeper node would be drawn. */
  full: boolean;
}

function pickNodes(
  nodes: Hierarchy.Node.Map,
  pointBudget: number,
  recordLength: number,
  fileSize: number | null,
  belowDepth = Number.POSITIVE_INFINITY,
): Picked {
  if (!Number.isSafeInteger(recordLength) || recordLength <= 0) return { selected: [], full: false };
  const usable: [number, string, Hierarchy.Node][] = [];
  for (const [key, node] of Object.entries(nodes)) {
    const depth = usableDepth(key, node, recordLength, fileSize);
    if (depth === null || depth >= belowDepth) continue;
    usable.push([depth, key, node as Hierarchy.Node]);
  }
  usable.sort((a, b) => a[0] - b[0]);
  const selected: [string, Hierarchy.Node][] = [];
  let points = 0;
  let bytes = 0;
  let large = 0;
  let full = false;
  for (const [, key, node] of usable) {
    // Stop before the point, node-count or byte budget, so a load never aborts
    // partway on its read budget with a half-drawn cloud.
    if (points + node.pointCount > pointBudget) {
      full = true;
      break;
    }
    if (selected.length >= MAX_SELECTED_NODES || bytes + node.pointDataLength > MAX_SELECTED_BYTES) {
      full = true;
      break;
    }
    const isLarge = node.pointDataLength > CHEAP_RANGE_BYTES;
    if (isLarge && large >= MAX_LARGE_NODES) continue;
    if (isLarge) large += 1;
    selected.push([key, node]);
    points += node.pointCount;
    bytes += node.pointDataLength;
  }
  return { selected, full: full || selected.length >= MAX_SELECTED_NODES || points >= pointBudget };
}

/**
 * The hierarchy nodes to draw: coarsest first, each within the per-node caps,
 * until the point, node-count or byte budget is spent. Entries a crafted file could use to inflate
 * a read or an allocation (non-finite or oversized counts and lengths,
 * malformed keys, a record length that makes the decoded node too big) are
 * dropped rather than trusted.
 */
export function selectNodes(
  nodes: Hierarchy.Node.Map,
  pointBudget: number,
  recordLength: number,
  fileSize: number | null,
): [string, Hierarchy.Node][] {
  return pickNodes(nodes, pointBudget, recordLength, fileSize).selected;
}

/** Whether the nodes shallower than `depth` already fill the selection, so nothing deeper would be drawn. */
export function selectionFullAbove(
  nodes: Hierarchy.Node.Map,
  depth: number,
  pointBudget: number,
  recordLength: number,
  fileSize: number | null,
): boolean {
  return pickNodes(nodes, pointBudget, recordLength, fileSize, depth).full;
}
