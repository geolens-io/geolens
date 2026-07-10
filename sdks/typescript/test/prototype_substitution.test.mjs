/**
 * GHSA-hhx9-57xq-r5rw: prefixed extra-param keys must not replace a request
 * slot's prototype through the legacy `$<slot>___proto__` substitution path.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildClientParams } from '../dist/client/client/index.js';

test('unknown prefixed __proto__ key cannot replace a params slot prototype', () => {
  const attackerPrototype = { inheritedSentinel: 'SYNTHETIC_SENTINEL' };
  const payload = Object.create(null);
  payload.$query___proto__ = attackerPrototype;

  const params = buildClientParams([payload], [{ allowExtra: { query: true } }]);

  assert.notEqual(Object.getPrototypeOf(params.query), attackerPrototype);
  assert.equal(params.query.inheritedSentinel, undefined);
  assert.equal(Object.hasOwn(params.query, '__proto__'), true);
  assert.deepEqual(params.query.__proto__, attackerPrototype);
});
