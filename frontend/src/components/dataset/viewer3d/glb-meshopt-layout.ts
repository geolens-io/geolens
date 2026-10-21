/**
 * Give each meshopt-compressed bufferView its own range of its fallback buffer.
 *
 * loaders.gl 4.5.3 decodes every compressed view in place into the fallback
 * buffer at the view's byteOffset. Some producers (the 3DBAG tiles among them)
 * leave every view at offset 0 of a data-less fallback buffer, so each decode
 * overwrites the previous one and the index buffer ends up holding vertex
 * bytes. Only the JSON chunk changes: a fallback buffer carries no stored
 * bytes, so moving its views and growing its byteLength reads nothing new.
 *
 * Returns the input unchanged when it is not a GLB or no fallback views overlap.
 */
export function separateMeshoptFallbackViews(glb: ArrayBuffer): ArrayBuffer {
  const view = new DataView(glb);
  if (glb.byteLength < 20 || view.getUint32(0, true) !== 0x46546c67) return glb;
  const jsonLength = view.getUint32(12, true);
  if (view.getUint32(16, true) !== 0x4e4f534a) return glb;
  const json = JSON.parse(new TextDecoder().decode(new Uint8Array(glb, 20, jsonLength))) as GltfJson;

  const fallback = new Set<number>();
  (json.buffers ?? []).forEach((buffer, index) => {
    const ext = buffer.extensions?.EXT_meshopt_compression ?? buffer.extensions?.KHR_meshopt_compression;
    if (ext?.fallback) fallback.add(index);
  });
  let changed = false;
  for (const bufferIndex of fallback) {
    const views = (json.bufferViews ?? []).filter((v) => v.buffer === bufferIndex);
    if (!overlaps(views)) continue;
    let offset = 0;
    for (const v of views) {
      v.byteOffset = offset;
      offset = align(offset + v.byteLength, 16);
    }
    json.buffers![bufferIndex].byteLength = offset;
    changed = true;
  }
  if (!changed) return glb;

  const encoded = new TextEncoder().encode(JSON.stringify(json));
  const paddedJson = align(encoded.byteLength, 4);
  const rest = new Uint8Array(glb, 20 + jsonLength);
  const out = new Uint8Array(12 + 8 + paddedJson + rest.byteLength);
  const outView = new DataView(out.buffer);
  out.set(new Uint8Array(glb, 0, 12));
  outView.setUint32(8, out.byteLength, true);
  outView.setUint32(12, paddedJson, true);
  outView.setUint32(16, 0x4e4f534a, true);
  out.set(encoded, 20);
  out.fill(0x20, 20 + encoded.byteLength, 20 + paddedJson);
  out.set(rest, 20 + paddedJson);
  return out.buffer;
}

interface GltfJson {
  buffers?: { byteLength: number; extensions?: Record<string, { fallback?: boolean } | undefined> }[];
  bufferViews?: { buffer: number; byteOffset?: number; byteLength: number }[];
}

function overlaps(views: { byteOffset?: number; byteLength: number }[]): boolean {
  const ranges = views
    .map((v) => [v.byteOffset ?? 0, (v.byteOffset ?? 0) + v.byteLength] as const)
    .sort((a, b) => a[0] - b[0]);
  return ranges.some((r, i) => i > 0 && r[0] < ranges[i - 1][1]);
}

function align(n: number, to: number): number {
  return Math.ceil(n / to) * to;
}
