import assert from 'node:assert/strict';
import { test } from 'node:test';

import { countdown, dayKey, daysAgo, firstName, humanize, initials, maskEmail, partOfDay, toDate } from '../src/lib/format.ts';

test('server instants without an offset are UTC', () => {
  assert.equal(toDate('2026-11-19T10:00:00')?.toISOString(), '2026-11-19T10:00:00.000Z');
  assert.equal(toDate('2026-11-19 10:00')?.toISOString(), '2026-11-19T10:00:00.000Z');
  assert.equal(toDate('2026-11-19T10:00:00+03:00')?.toISOString(), '2026-11-19T07:00:00.000Z');
  assert.equal(toDate(''), null);
  assert.equal(toDate('not a date'), null);
  assert.equal(toDate(null), null);
});

test('calendar helpers', () => {
  const now = new Date(2026, 10, 19, 9, 0);
  assert.equal(daysAgo(new Date(2026, 10, 19, 1, 0), now), 0);
  assert.equal(daysAgo(new Date(2026, 10, 18, 23, 0), now), 1);
  assert.equal(dayKey(null), 'unknown');
  assert.equal(partOfDay(new Date(2026, 0, 1, 8)), 'morning');
  assert.equal(partOfDay(new Date(2026, 0, 1, 13)), 'afternoon');
  assert.equal(partOfDay(new Date(2026, 0, 1, 20)), 'evening');
  assert.equal(countdown(65), '1:05');
  assert.equal(countdown(-3), '0:00');
});

test('names and text', () => {
  assert.equal(firstName('  ada lovelace '), 'Ada');
  assert.equal(firstName(undefined), '');
  assert.equal(initials('Ada Lovelace'), 'AL');
  assert.equal(initials(''), '?');
  assert.equal(humanize('account_banned'), 'Account banned');
  assert.equal(maskEmail('ada@example.com'), 'a•••@example.com');
  assert.equal(maskEmail('nope'), 'nope');
});
