import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { test } from 'node:test';

import { DEVICE_ID_LENGTH, getOrCreateDeviceId, isValidDeviceId, makeDeviceId } from '../src/lib/device-id.ts';

const random = (n: number) => new Uint8Array(randomBytes(n));

function memoryStore(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  let writes = 0;
  return {
    getItem: async (key: string) => data.get(key) ?? null,
    setItem: async (key: string, value: string) => {
      writes++;
      data.set(key, value);
    },
    get writes() {
      return writes;
    },
  };
}

test('generated ids match the backend rule: 32-128 chars of A-Za-z0-9_-', () => {
  for (let i = 0; i < 200; i++) {
    const id = makeDeviceId(random);
    assert.equal(id.length, DEVICE_ID_LENGTH);
    assert.match(id, /^[A-Za-z0-9_-]{32,128}$/);
  }
  assert.equal(makeDeviceId(random, 32).length, 32);
  assert.equal(makeDeviceId(random, 128).length, 128);
  assert.throws(() => makeDeviceId(random, 31));
  assert.throws(() => makeDeviceId(random, 129));
  assert.notEqual(makeDeviceId(random), makeDeviceId(random));
});

test('validation', () => {
  assert.equal(isValidDeviceId('a'.repeat(32)), true);
  assert.equal(isValidDeviceId('a'.repeat(31)), false);
  assert.equal(isValidDeviceId('a'.repeat(129)), false);
  assert.equal(isValidDeviceId(`${'a'.repeat(40)}!`), false);
  assert.equal(isValidDeviceId(null), false);
});

test('created once per install, then read back', async () => {
  const store = memoryStore();
  const first = await getOrCreateDeviceId(store, 'device', random);
  const second = await getOrCreateDeviceId(store, 'device', random);
  assert.equal(first, second);
  assert.equal(store.writes, 1);
});

test('a malformed stored id is replaced', async () => {
  const store = memoryStore({ device: 'short' });
  const id = await getOrCreateDeviceId(store, 'device', random);
  assert.ok(isValidDeviceId(id));
  assert.equal(await store.getItem('device'), id);
});
