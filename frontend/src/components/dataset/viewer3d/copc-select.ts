import type { Hierarchy } from 'copc';
import { MAX_NODE_DECODED_BYTES, MAX_RANGE_BYTES, POINT_BUDGET } from './copc-limits';

const NODE_KEY = /^(\d{1,2})-(-?\d{1,9})-(-?\d{1,9})-(-?\d{1,9})$/;

/**
 * The hierarchy nodes to draw: coarsest first, each within the per-node caps,
 * until the point budget is spent. Entries a crafted file could use to inflate
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
  if (!Number.isSafeInteger(recordLength) || recordLength <= 0) return [];
  const usable: [number, string, Hierarchy.Node][] = [];
  for (const [key, node] of Object.entries(nodes)) {
    const depth = NODE_KEY.exec(key)?.[1];
    if (!node || depth === undefined) continue;
    const { pointCount, pointDataOffset, pointDataLength } = node;
    if (!Number.isSafeInteger(pointCount) || pointCount <= 0 || pointCount > POINT_BUDGET) continue;
    if (pointCount * recordLength > MAX_NODE_DECODED_BYTES) continue;
    if (!Number.isSafeInteger(pointDataOffset) || pointDataOffset < 0) continue;
    if (!Number.isSafeInteger(pointDataLength) || pointDataLength <= 0 || pointDataLength > MAX_RANGE_BYTES) continue;
    if (fileSize !== null && pointDataOffset + pointDataLength > fileSize) continue;
    usable.push([Number(depth), key, node]);
  }
  usable.sort((a, b) => a[0] - b[0]);
  const selected: [string, Hierarchy.Node][] = [];
  let points = 0;
  for (const [, key, node] of usable) {
    if (points + node.pointCount > pointBudget) break;
    selected.push([key, node]);
    points += node.pointCount;
  }
  return selected;
}
