// The COPC file is untrusted input: every size below bounds an allocation or a
// loop that a crafted header, VLR or hierarchy entry could otherwise inflate.

/** The COPC route serves ranges up to this size without extra rate cost. */
export const MAX_RANGE_BYTES = 16 * 1024 * 1024;
/** Reads and bytes one load may issue; the route allows 1200 reads and 1 GiB a minute. */
export const MAX_LOAD_READS = 400;
export const MAX_LOAD_BYTES = 256 * 1024 * 1024;
export const MAX_CONCURRENT_READS = 4;
export const MAX_RETRIES = 4;

// One node may hold the whole budget; the decoded-size cap below bounds it in bytes.
export const POINT_BUDGET = 2_000_000;
/** Decoded bytes (points times record length) one node may occupy. */
export const MAX_NODE_DECODED_BYTES = 128 * 1024 * 1024;
export const MAX_WKT_LENGTH = 32 * 1024;
