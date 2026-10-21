/**
 * Bits to shift LAS colour down to 8 bits. The fields are 16-bit, but some
 * writers store 8-bit values in them; a cloud whose brightest channel fits in
 * a byte is taken as already 8-bit.
 */
export function colorShiftFor(maxChannel: number): 0 | 8 {
  return maxChannel > 255 ? 8 : 0;
}
