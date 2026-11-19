import { z } from 'zod';

/**
 * Form rules (pure, tested in tests/validation.test.ts). Problems are returned as i18n keys
 * (see src/i18n/en.json "validation"); screens translate them with t().
 */
export const PROBLEMS = {
  emailMissing: 'validation.emailMissing',
  emailInvalid: 'validation.emailInvalid',
  passwordMissing: 'validation.passwordMissing',
  code: 'validation.code',
} as const;

const emailShape = z.email().max(254);

/** Trimmed, lower-cased email as it is sent to the server. */
export function normalizeEmail(value: string) {
  return value.trim().toLowerCase();
}

export function emailProblem(value: string): string | null {
  const email = normalizeEmail(value);
  if (!email) return PROBLEMS.emailMissing;
  return emailShape.safeParse(email).success ? null : PROBLEMS.emailInvalid;
}

export function strongPassword(value: string) {
  return (
    value.length >= 8 &&
    value.length <= 120 &&
    /[A-Z]/.test(value) &&
    /[a-z]/.test(value) &&
    /[0-9]/.test(value) &&
    /[!"#$%&'()*+,\-./:;<=>?@[\]^_`{|}~]/.test(value)
  );
}

export function codeProblem(value: string) {
  return /^[0-9]{6}$/.test(value) ? null : PROBLEMS.code;
}

/** Sign-in form schema (react-hook-form resolver). Messages are i18n keys. */
export const signInSchema = z.object({
  email: z.string().superRefine((value, ctx) => {
    const problem = emailProblem(value);
    if (problem) ctx.addIssue({ code: 'custom', message: problem });
  }),
  password: z.string().min(1, PROBLEMS.passwordMissing),
});
