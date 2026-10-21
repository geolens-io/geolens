// The COPC file is untrusted input: every size below bounds an allocation or a
// loop that a crafted header, VLR or hierarchy entry could otherwise inflate.

/** One range read: ingestion accepts compressed and decoded nodes up to 64 MiB (larger ranges cost more of the route's byte limit). */
export const MAX_RANGE_BYTES = 64 * 1024 * 1024;
/** Reads and bytes one load may issue; the route allows 1200 reads and 1 GiB a minute. */
export const MAX_LOAD_READS = 400;
export const MAX_LOAD_BYTES = 256 * 1024 * 1024;
/** Range size the route serves under its cheap per-minute limit (_EXEMPT_RANGE_BYTES in router_pointcloud.py). */
export const CHEAP_RANGE_BYTES = 16 * 1024 * 1024;
/** Nodes above that size one load reads; the route rate-limits larger ranges more tightly. */
export const MAX_LARGE_NODES = 8;
/** Nodes one load draws, leaving room in the read budget for the header, VLRs and hierarchy. */
export const MAX_SELECTED_NODES = MAX_LOAD_READS - 100;
/** Compressed bytes of the selected nodes, leaving room in the byte budget for the rest. */
export const MAX_SELECTED_BYTES = MAX_LOAD_BYTES - 32 * 1024 * 1024;
export const MAX_CONCURRENT_READS = 4;
export const MAX_RETRIES = 4;

// One node may hold the whole budget; the decoded-size cap below bounds it in bytes.
export const POINT_BUDGET = 2_000_000;
/** Decoded bytes (points times record length) one node may occupy. */
export const MAX_NODE_DECODED_BYTES = 128 * 1024 * 1024;
export const MAX_WKT_LENGTH = 64 * 1024;
