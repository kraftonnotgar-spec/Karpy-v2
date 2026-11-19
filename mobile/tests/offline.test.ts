import assert from 'node:assert/strict';
import { test } from 'node:test';

import { isOfflineState, lastUpdatedTime, newest, shouldPersistKey, utf8Decode, utf8Encode } from '../src/lib/offline/rules.ts';

test('offline only when the OS is sure', () => {
  assert.equal(isOfflineState({ isConnected: false }), true);
  assert.equal(isOfflineState({ isConnected: true, isInternetReachable: false }), true);
  assert.equal(isOfflineState({ isConnected: true, isInternetReachable: true }), false);
  // still checking: never block the app
  assert.equal(isOfflineState({ isConnected: null, isInternetReachable: null }), false);
  assert.equal(isOfflineState({ isConnected: true, isInternetReachable: null }), false);
});

test('only allow-listed read-only queries are saved on the device', () => {
  assert.equal(shouldPersistKey(['me']), true);
  assert.equal(shouldPersistKey(['notifications']), true);
  assert.equal(shouldPersistKey(['me', 'extra']), false);
  assert.equal(shouldPersistKey(['sessions']), false);
  assert.equal(shouldPersistKey([{ me: true }]), false);
  assert.equal(shouldPersistKey(['orders'], ['orders']), true);
});

test('last updated time', () => {
  const now = new Date(2026, 10, 19, 15, 0).getTime();
  assert.equal(lastUpdatedTime(new Date(2026, 10, 19, 14, 32).getTime(), now), '14:32');
  assert.equal(lastUpdatedTime(new Date(2026, 10, 3, 9, 5).getTime(), now), '3/11 09:05');
  assert.equal(lastUpdatedTime(0, now), null);
  assert.equal(newest(undefined, 5, 3), 5);
  assert.equal(newest(), 0);
});

test('UTF-8 round trip for the encrypted cache file', () => {
  for (const text of ['', 'plain', 'Café ✓', 'emoji 😀 and 中文', JSON.stringify({ a: 'ü'.repeat(5000) })]) {
    const bytes = utf8Encode(text);
    assert.deepEqual(Array.from(bytes), Array.from(new TextEncoder().encode(text)));
    assert.equal(utf8Decode(bytes), text);
  }
});
