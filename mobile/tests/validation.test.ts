import assert from 'node:assert/strict';
import { test } from 'node:test';

import { codeProblem, emailProblem, normalizeEmail, PROBLEMS, signInSchema, strongPassword } from '../src/lib/validation.ts';

test('incomplete emails are refused', () => {
  for (const bad of ['ada', 'ada@', 'ada@example', '@example.com', 'ada@example.', 'a da@example.com']) {
    assert.equal(emailProblem(bad), PROBLEMS.emailInvalid, bad);
  }
  assert.equal(emailProblem('   '), PROBLEMS.emailMissing);
  assert.equal(emailProblem('  Ada@Example.co.uk '), null);
  assert.equal(normalizeEmail('  Ada@Example.co.uk '), 'ada@example.co.uk');
});

test('sign-in needs a valid email and a password', () => {
  assert.equal(signInSchema.safeParse({ email: 'a@b.co', password: 'x' }).success, true);
  const missing = signInSchema.safeParse({ email: 'a@b', password: '' });
  assert.equal(missing.success, false);
  const messages = missing.error!.issues.map((i) => i.message);
  assert.ok(messages.includes(PROBLEMS.emailInvalid));
  assert.ok(messages.includes(PROBLEMS.passwordMissing));
});

test('password strength and six-digit codes', () => {
  assert.equal(strongPassword('Abcdef1!'), true);
  assert.equal(strongPassword('abcdef1!'), false);
  assert.equal(strongPassword('Abcdefg!'), false);
  assert.equal(strongPassword('Ab1!'), false);
  assert.equal(codeProblem('123456'), null);
  assert.equal(codeProblem('12345'), PROBLEMS.code);
  assert.equal(codeProblem('12a456'), PROBLEMS.code);
});
