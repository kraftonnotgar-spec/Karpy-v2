import assert from 'node:assert/strict';
import { test } from 'node:test';

import { closureFromResponse, isStaffRefusal } from '../src/lib/auth/account-status.ts';
import { createRefresher, usableAccessToken, type RefresherDeps, type Tokens } from '../src/lib/auth/refresh.ts';

function tokens(n: number): Tokens {
  return { token_type: 'Bearer', access_token: `access-${n}`, expires_in: 900, refresh_token: `refresh-${n}`, refresh_expires_in: 2592000 };
}

function setup(callRefresh: RefresherDeps['callRefresh']) {
  const state = { stored: 'refresh-0' as string | null, order: [] as string[], closed: [] as unknown[], sent: [] as unknown[] };
  const refresh = createRefresher({
    readRefreshToken: async () => state.stored,
    saveRefreshToken: async (token) => {
      state.order.push(`save:${token}`);
      state.stored = token;
    },
    deviceId: async () => 'd'.repeat(43),
    callRefresh: async (body) => {
      state.sent.push(body);
      return callRefresh(body);
    },
    onTokens: (t) => state.order.push(`use:${t.access_token}`),
    onClosed: (closure) => {
      state.closed.push(closure);
    },
  });
  return { refresh, state };
}

test('refresh rotates: the new refresh token is stored before the access token is used', async () => {
  const { refresh, state } = setup(async () => tokens(1));
  assert.equal(await refresh(), 'access-1');
  assert.deepEqual(state.sent, [{ refresh_token: 'refresh-0', device_id: 'd'.repeat(43) }]);
  assert.equal(state.stored, 'refresh-1');
  assert.deepEqual(state.order, ['save:refresh-1', 'use:access-1']);
});

test('no stored refresh token: nothing to refresh', async () => {
  const { refresh, state } = setup(async () => tokens(1));
  state.stored = null;
  assert.equal(await refresh(), null);
  assert.equal(state.sent.length, 0);
});

test('401 means sign in again (resolves null, token kept for the sign-out to clear)', async () => {
  const { refresh, state } = setup(async () => {
    throw { status: 401, body: { detail: 'This session is no longer valid.' } };
  });
  assert.equal(await refresh(), null);
  assert.equal(state.closed.length, 0);
});

test('403 with a closed-account code closes the account', async () => {
  const { refresh, state } = setup(async () => {
    throw { status: 403, body: { detail: 'Your account is banned.', code: 'account_banned', reason: '  Fraud\n review ' } };
  });
  assert.equal(await refresh(), null);
  assert.deepEqual(state.closed, [{ status: 'banned', reason: 'Fraud review' }]);
});

test('network failures and 5xx keep the session (the refresh rejects)', async () => {
  const offline = setup(async () => {
    throw { status: 0, code: 'network' };
  });
  await assert.rejects(offline.refresh());
  const down = setup(async () => {
    throw { status: 503, body: { detail: 'busy' } };
  });
  await assert.rejects(down.refresh());
  assert.equal(down.state.stored, 'refresh-0');
});

test('closed accounts are recognised in refresh and login shapes only on 403', () => {
  assert.deepEqual(closureFromResponse(403, { detail: 'x', code: 'account_deactivated', reason: null }), { status: 'deactivated', reason: null });
  assert.deepEqual(closureFromResponse(403, { detail: { form: 'x', accountStatus: 'banned', code: 'account_banned', reason: 'Spam' } }), {
    status: 'banned',
    reason: 'Spam',
  });
  assert.deepEqual(closureFromResponse(403, { detail: { form: 'x', accountStatus: 'deactivated' } }), { status: 'deactivated', reason: null });
  assert.equal(closureFromResponse(401, { code: 'account_banned' }), null);
  assert.equal(closureFromResponse(403, { detail: { form: 'x', mobileAccess: 'staff_not_allowed' } }), null);
  assert.equal(isStaffRefusal(403, { detail: { form: 'x', mobileAccess: 'staff_not_allowed' } }), true);
  assert.equal(isStaffRefusal(403, { detail: 'x' }), false);
});

test('access tokens count as expired 10 s early', () => {
  assert.equal(usableAccessToken('a', 1_000_000, 1_000_000 - 20_000), 'a');
  assert.equal(usableAccessToken('a', 1_000_000, 1_000_000 - 5_000), null);
  assert.equal(usableAccessToken(null, 1_000_000, 0), null);
});
