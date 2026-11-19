import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createApiClient, type ClientDeps } from '../src/lib/api/client.ts';
import { ApiError, errorFromResponse, isNetworkFailure } from '../src/lib/api/errors.ts';

type Call = { url: string; method: string; auth: string | null; body: unknown };

function json(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(body === undefined ? '' : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
}

/** A fake backend: `handler` decides each answer; every call is recorded. */
function setup(handler: (call: Call) => Response | Promise<Response>, overrides: Partial<ClientDeps> = {}) {
  const calls: Call[] = [];
  let access: string | null = 'old-token';
  let refreshes = 0;
  let lost = 0;
  const deps: ClientDeps = {
    baseUrl: 'https://api.test',
    fetch: (async (input: string, init?: RequestInit) => {
      const headers = (init?.headers ?? {}) as Record<string, string>;
      const call = { url: String(input), method: init?.method ?? 'GET', auth: headers.Authorization ?? null, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      return handler(call);
    }) as typeof fetch,
    getAccessToken: () => access,
    refresh: async () => {
      refreshes++;
      await new Promise((r) => setTimeout(r, 5));
      access = 'new-token';
      return access;
    },
    onSessionLost: () => {
      lost++;
    },
    ...overrides,
  };
  const client = createApiClient(deps);
  return {
    client,
    calls,
    get refreshes() {
      return refreshes;
    },
    get lost() {
      return lost;
    },
    setAccess: (value: string | null) => {
      access = value;
    },
  };
}

test('private requests carry the bearer token and parse JSON', async () => {
  const h = setup(() => json(200, { user: { name: 'Ada' } }));
  const me = await h.client.get<{ user: { name: string } }>('/me');
  assert.equal(me.user.name, 'Ada');
  assert.equal(h.calls[0].url, 'https://api.test/me');
  assert.equal(h.calls[0].auth, 'Bearer old-token');
});

test('public requests never carry a bearer and never refresh', async () => {
  const h = setup(() => json(401, { detail: 'nope' }));
  await assert.rejects(h.client.post('/login', { email: 'a@b.co' }, { public: true }), (e: ApiError) => e.status === 401);
  assert.equal(h.calls[0].auth, null);
  assert.deepEqual(h.calls[0].body, { email: 'a@b.co' });
  assert.equal(h.refreshes, 0);
  assert.equal(h.lost, 0);
});

test('a 401 refreshes once and retries with the new token', async () => {
  const h = setup((call) => (call.auth === 'Bearer new-token' ? json(200, { ok: true }) : json(401, { detail: 'This session is no longer valid.' })));
  const result = await h.client.get<{ ok: boolean }>('/me');
  assert.equal(result.ok, true);
  assert.equal(h.refreshes, 1);
  assert.deepEqual(
    h.calls.map((c) => c.auth),
    ['Bearer old-token', 'Bearer new-token'],
  );
});

test('parallel 401s share a single refresh (single flight)', async () => {
  const h = setup((call) => (call.auth === 'Bearer new-token' ? json(200, { ok: true }) : json(401, {})));
  await Promise.all([h.client.get('/a'), h.client.get('/b'), h.client.get('/c')]);
  assert.equal(h.refreshes, 1);
});

test('no access token in memory: refresh before sending', async () => {
  const h = setup(() => json(200, {}));
  h.setAccess(null);
  await h.client.get('/me');
  assert.equal(h.refreshes, 1);
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].auth, 'Bearer new-token');
});

test('a refused refresh ends the session', async () => {
  const h = setup(() => json(401, { detail: 'This session is no longer valid.' }), { refresh: async () => null });
  await assert.rejects(h.client.get('/me'), (e: ApiError) => e.status === 401 && e.message === 'This session is no longer valid.');
  assert.equal(h.lost, 1);
});

test('a refresh that cannot reach the server keeps the session', async () => {
  const h = setup(() => json(401, {}), {
    refresh: async () => {
      throw new ApiError('', 0, 'network');
    },
  });
  await assert.rejects(h.client.get('/me'), (e: ApiError) => e.code === 'network');
  assert.equal(h.lost, 0);
});

test('offline fails at once without calling fetch', async () => {
  const h = setup(() => json(200, {}), { isOffline: () => true });
  await assert.rejects(h.client.get('/me'), (e: ApiError) => e.code === 'offline' && isNetworkFailure(e));
  assert.equal(h.calls.length, 0);
});

test('a thrown fetch becomes a network error; a slow one a timeout', async () => {
  const down = setup(() => {
    throw new TypeError('Network request failed');
  });
  await assert.rejects(down.client.get('/me'), (e: ApiError) => e.code === 'network' && e.status === 0);

  const slow = setup(() => new Promise<Response>(() => {}), {
    fetch: ((_: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
      })) as typeof fetch,
    timeoutMs: 20,
  });
  await assert.rejects(slow.client.get('/me'), (e: ApiError) => e.code === 'timeout');
});

test('DELETE sends a JSON body (push-devices)', async () => {
  const h = setup(() => json(200, { removed: true }));
  const result = await h.client.del<{ removed: boolean }>('/push-devices', { device_id: 'x'.repeat(43) });
  assert.equal(result.removed, true);
  assert.equal(h.calls[0].method, 'DELETE');
  assert.deepEqual(h.calls[0].body, { device_id: 'x'.repeat(43) });
});

test('FastAPI errors become ApiError: fields, form, codes', () => {
  const creds = errorFromResponse(422, { detail: { email: 'These credentials do not match our records.' } });
  assert.equal(creds.fields.email, 'These credentials do not match our records.');
  assert.equal(creds.message, 'These credentials do not match our records.');
  assert.equal(creds.code, 'http_422');

  const staff = errorFromResponse(403, { detail: { form: 'Staff accounts cannot use the mobile app.', mobileAccess: 'staff_not_allowed' } });
  assert.equal(staff.code, 'staff_not_allowed');
  assert.equal(staff.message, 'Staff accounts cannot use the mobile app.');
  assert.deepEqual(staff.fields, {});

  const closed = errorFromResponse(403, { detail: 'Account deactivated.', code: 'account_deactivated', reason: null });
  assert.equal(closed.code, 'account_deactivated');
  assert.equal(closed.message, 'Account deactivated.');

  // verify-login names the *field* "code": its text is a field message, not a machine code.
  const wrongCode = errorFromResponse(422, { detail: { code: 'The sign-in code is invalid or expired.' } });
  assert.equal(wrongCode.code, 'http_422');
  assert.equal(wrongCode.fields.code, 'The sign-in code is invalid or expired.');

  const limited = errorFromResponse(429, { detail: { form: 'Too many sign-in attempts.' } }, '120');
  assert.equal(limited.code, 'rate_limited');
  assert.equal(limited.retryAfter, 120);

  const pydantic = errorFromResponse(422, { detail: [{ loc: ['body', 'email'], msg: 'field required' }] });
  assert.equal(pydantic.message, 'field required');

  assert.equal(errorFromResponse(500, undefined).message, '');
});
