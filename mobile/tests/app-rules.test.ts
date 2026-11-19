import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { createTranslator, format, lookup, type Catalog } from '../src/i18n/translate.ts';
import { MAX_ATTEMPTS, remainingAttempts, shouldLock, weakPin } from '../src/lib/auth/pin-rules.ts';
import { providerForNativeToken, pushMode, safePushHref } from '../src/lib/push-rules.ts';

const en = JSON.parse(readFileSync(new URL('../src/i18n/en.json', import.meta.url), 'utf8')) as Catalog;

test('weak PINs are refused', () => {
  for (const pin of ['1111', '1234', '4321', '9012', '2580']) assert.equal(weakPin(pin), true, pin);
  for (const pin of ['3851', '7604']) assert.equal(weakPin(pin), false, pin);
  assert.equal(remainingAttempts(MAX_ATTEMPTS), 0);
  assert.equal(remainingAttempts(1), MAX_ATTEMPTS - 1);
});

test('auto-lock after the configured background time', () => {
  assert.equal(shouldLock(null, 100_000, 60_000), false);
  assert.equal(shouldLock(0, 59_999, 60_000), false);
  assert.equal(shouldLock(0, 60_000, 60_000), true);
});

test('push providers and safe deep links', () => {
  assert.equal(providerForNativeToken('ios'), 'apns');
  assert.equal(providerForNativeToken('android'), 'fcm');
  assert.equal(providerForNativeToken('web'), null);
  assert.equal(pushMode('expo'), 'expo');
  assert.equal(pushMode(undefined), 'native');
  assert.equal(safePushHref('/settings'), '/settings');
  assert.equal(safePushHref('https://evil.example'), null);
  assert.equal(safePushHref('/unknown'), null);
});

test('translations: lookup, placeholders, fallback to the key', () => {
  const t = createTranslator([en]);
  assert.equal(t('common.cancel'), 'Cancel');
  assert.equal(t('unlock.wrongPin', { remaining: 3 }), 'Wrong PIN. 3 tries left.');
  assert.equal(t('missing.key'), 'missing.key');
  assert.equal(format('{a} and {b}', { a: 1 }), '1 and {b}');
  assert.equal(lookup(en, 'common'), undefined);
  // every API error code the client can produce on its own has app wording
  for (const code of ['generic', 'offline', 'network', 'timeout', 'rate_limited', 'session_expired', 'staff_not_allowed']) {
    assert.equal(typeof lookup(en, `errors.${code}`), 'string', code);
  }
});
