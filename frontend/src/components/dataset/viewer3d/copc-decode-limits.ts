import {
  MAX_NODE_DECODED_BYTES,
  MAX_NODE_POINTS,
  MAX_RANGE_BYTES,
  MAX_WKT_LENGTH,
} from './copc-limits';

interface DecodeInput {
  node: { pointCount: number };
  bytes: ArrayBuffer;
  copc: { header: { pointDataRecordLength: number } };
  horizontalWkt: string;
  zToMeters: number;
  origin: number[];
}

/** Throws unless a decode request stays inside the caps; the worker's own check on what the main thread posts. */
export function checkDecodeLimits({ node, bytes, copc, horizontalWkt, zToMeters, origin }: DecodeInput) {
  const recordLength = copc.header.pointDataRecordLength;
  if (!Number.isSafeInteger(node.pointCount) || node.pointCount <= 0 || node.pointCount > MAX_NODE_POINTS) {
    throw new Error('node point count outside the cap');
  }
  if (!Number.isSafeInteger(recordLength) || recordLength <= 0 || node.pointCount * recordLength > MAX_NODE_DECODED_BYTES) {
    throw new Error('node would decode past the size cap');
  }
  if (bytes.byteLength > MAX_RANGE_BYTES) throw new Error('compressed node outside the cap');
  if (horizontalWkt.length > MAX_WKT_LENGTH) throw new Error('CRS outside the cap');
  if (!Number.isFinite(zToMeters) || !origin.every(Number.isFinite)) throw new Error('invalid placement');
}
