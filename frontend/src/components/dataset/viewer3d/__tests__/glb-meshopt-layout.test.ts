import { describe, expect, it } from 'vitest';
import { separateMeshoptFallbackViews } from '../glb-meshopt-layout';

function glb(json: object): ArrayBuffer {
  const encoded = new TextEncoder().encode(JSON.stringify(json));
  const padded = Math.ceil(encoded.byteLength / 4) * 4;
  const out = new Uint8Array(20 + padded + 8);
  const view = new DataView(out.buffer);
  view.setUint32(0, 0x46546c67, true);
  view.setUint32(4, 2, true);
  view.setUint32(8, out.byteLength, true);
  view.setUint32(12, padded, true);
  view.setUint32(16, 0x4e4f534a, true);
  out.set(encoded, 20);
  out.fill(0x20, 20 + encoded.byteLength, 20 + padded);
  return out.buffer;
}

function jsonOf(buffer: ArrayBuffer) {
  const length = new DataView(buffer).getUint32(12, true);
  return JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 20, length)));
}

const fallbackBuffer = { byteLength: 100, extensions: { EXT_meshopt_compression: { fallback: true } } };

describe('separateMeshoptFallbackViews', () => {
  it('lays overlapping fallback views out one after another', () => {
    const out = separateMeshoptFallbackViews(
      glb({
        buffers: [fallbackBuffer],
        bufferViews: [
          { buffer: 0, byteOffset: 0, byteLength: 40 },
          { buffer: 0, byteOffset: 0, byteLength: 24 },
        ],
      }),
    );
    const json = jsonOf(out);
    expect(json.bufferViews.map((v: { byteOffset: number }) => v.byteOffset)).toEqual([0, 48]);
    expect(json.buffers[0].byteLength).toBe(80);
  });

  it('returns the input unchanged when the views do not overlap', () => {
    const input = glb({
      buffers: [fallbackBuffer],
      bufferViews: [
        { buffer: 0, byteOffset: 0, byteLength: 40 },
        { buffer: 0, byteOffset: 40, byteLength: 24 },
      ],
    });
    expect(separateMeshoptFallbackViews(input)).toBe(input);
  });

  it('returns a non-GLB unchanged', () => {
    const input = new ArrayBuffer(32);
    expect(separateMeshoptFallbackViews(input)).toBe(input);
  });
});
