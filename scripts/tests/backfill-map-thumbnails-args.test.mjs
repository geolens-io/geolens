// Run: node --test scripts/tests/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { isThumbnailUploadOk, parseArgs, selectMaps } from '../lib/backfill-map-thumbnails-args.mjs';

const maps = [
  { id: 'a', name: 'A', thumbnail_url: '/maps/a/thumbnail/' },
  { id: 'b', name: 'B', thumbnail_url: null },
  { id: 'c', name: 'C', thumbnail_url: '/maps/c/thumbnail/' },
];

test('parseArgs collects ids after --refresh and combines with --dry-run', () => {
  assert.deepEqual(parseArgs(['--refresh', 'a', 'c', '--dry-run']), {
    dryRun: true,
    includePublic: false,
    refresh: ['a', 'c'],
  });
});

test('parseArgs rejects --refresh without ids and unknown flags', () => {
  assert.throws(() => parseArgs(['--refresh']), /at least one map id/);
  assert.throws(() => parseArgs(['--refresh', '--dry-run']), /at least one map id/);
  assert.throws(() => parseArgs(['--bogus']), /unknown argument/);
});

test('selectMaps without refresh picks only thumbnail-less maps', () => {
  assert.deepEqual(selectMaps(maps, []).targets.map((m) => m.id), ['b']);
});

test('selectMaps with refresh picks named maps even when a thumbnail exists', () => {
  const { targets, unknown } = selectMaps(maps, ['a', 'c']);
  assert.deepEqual(targets.map((m) => m.id), ['a', 'c']);
  assert.deepEqual(unknown, []);
});

test('selectMaps reports ids the credential cannot see', () => {
  const { targets, unknown } = selectMaps(maps, ['a', 'zzz', 'a']);
  assert.deepEqual(targets.map((m) => m.id), ['a']);
  assert.deepEqual(unknown, ['zzz']);
});

test('isThumbnailUploadOk skips a failed PUT so a retried success counts', () => {
  const url = 'http://x/api/maps/a/thumbnail/';
  assert.equal(isThumbnailUploadOk('PUT', url, false, 'a'), false);
  assert.equal(isThumbnailUploadOk('PUT', url, true, 'a'), true);
  assert.equal(isThumbnailUploadOk('GET', url, true, 'a'), false);
  assert.equal(isThumbnailUploadOk('PUT', url, true, 'b'), false);
});
